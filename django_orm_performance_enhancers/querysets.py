import inspect
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TypeVar, Generic, Optional, Union, Type, List, Dict, Set
from typing_extensions import Self, DefaultDict

from django.db.models import Model, QuerySet, Prefetch

from django_orm_performance_enhancers.evaluation_callbacks import EvaluationCallbackType, get_prefetch_limiter, \
    MapRelatedCall, MapRelatedCondition, get_map_related_callback
from django_orm_performance_enhancers.select_related_hack import RelatedPopulatorMonkeypatch
from django_orm_performance_enhancers.utils import (
    find_model_by_path, get_related_id_from_obj_path, ModelIdType,
    set_related_obj_to_path_from_pool, get_relation_from_path, map_instances
)

TModel = TypeVar('TModel', bound=Model, covariant=True)

QuerySetType = QuerySet[TModel]


@dataclass
class PrefetchUnrelatedCall:
    qs: QuerySetType
    group_by_attr: str
    map_by_attr: str
    map_to_attr: str


@dataclass
class PoolRelatedCall:
    qs: QuerySetType
    related_fields: List[str]
    to_attr: Optional[str] = None

    def evaluate(self, results: List[Model]):
        ids_to_fetch: Set[ModelIdType] = set()

        for related_field in self.related_fields:
            for result in results:
                ids_to_fetch.add(get_related_id_from_obj_path(result, related_field))

        pool: Dict[ModelIdType, Model] = {x.id: x for x in self.qs.filter(id__in=ids_to_fetch)}

        for related_field in self.related_fields:
            for result in results:
                set_related_obj_to_path_from_pool(result, related_field, pool)

    def __repr__(self):
        return f'PoolRelatedCall({self.qs.model.__name__}, {self.related_fields})'


@dataclass
class ModelRelationsToPull(Generic[TModel]):
    related_fields: List[str] = field(default_factory=list)
    pool_related_calls: List[PoolRelatedCall] = field(default_factory=list)


class ExtendedQuerySet(QuerySet[TModel, TModel]):
    model: Type[TModel]

    _evaluation_callbacks: List[EvaluationCallbackType]
    _eval_callbacks_called: bool

    _pool_related_calls: DefaultDict[Type[Model], ModelRelationsToPull[TModel]]
    _pool_related_done: bool
    _pool_select_related: Optional[bool]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._evaluation_callbacks: List[EvaluationCallbackType] = []
        self._eval_callbacks_called = False
        self._pool_related_calls = defaultdict(ModelRelationsToPull)
        self._pool_related_done = False
        self._pool_select_related = None

    def with_evaluation_callbacks(self, *evaluation_callbacks: EvaluationCallbackType) -> Self:
        """
        Accepts callbacks with a single argument(resulting object list) as an argument.
         - All callbacks are called after you first evaluate your queryset.
         - All callbacks are being transferred to children querysets like `filter()` calls,
           so you can mix and match however you like.
         - Multiple callbacks can be added by calling this multiple times.
         - Callbacks are called in the order they were added.
        """
        clone = self._clone()
        clone._evaluation_callbacks.extend(evaluation_callbacks)
        return clone

    def pool_related(self, *pool_related_calls_or_paths: Union[str, PoolRelatedCall, None]) -> Self:
        """
        This is a drop-in replacement for prefetch_related.
        Accepts either relation paths or PoolRelatedCall objects.
        Passing None as single argument will clear all pool_related calls.
        """
        clone = self._clone()

        if len(pool_related_calls_or_paths) == 1 and pool_related_calls_or_paths[0] is None:
            clone._pool_related_calls.clear()
            return clone

        for call_or_path in filter(bool, pool_related_calls_or_paths):
            if isinstance(call_or_path, PoolRelatedCall):
                clone._pool_related_calls[call_or_path.qs.model].pool_related_calls.append(call_or_path)
            else:
                model = find_model_by_path(clone.model, call_or_path)
                clone._pool_related_calls[model].related_fields.append(call_or_path)
        return clone

    def select_related_pooled(self, *related_fields: Union[str, None]) -> Self:
        """
        This is a drop-in replacement for select_related.
        Accepts relation paths.

        If called like .select_related_pooled(None), it will clear all select_related calls.

        Since all select_related are evaluated inside SQL compiler,
        we can't granularly control which fields get pooled via select_related.

        It's either all model select_related calls are pooled or none.
        """
        clone = self.select_related(*related_fields)
        clone._pool_select_related = bool(clone.query.select_related)
        return clone

    def prefetch_related_with_limit(self,
                                    *fields_or_prefetches: Union[str, Prefetch],
                                    limit: Optional[int] = None) -> Self:
        """
        if `limits` is not provided, assumes LIMIT 1 for all fields and uses DISTINCT ON to get only one result.
        If `limits` is provided, manages limiting in python to achieve necessary result.

        Because it's not trivial to do limit 2 in SQL, we do it in python.
        """
        if limit is not None:
            limits = {}
            for f in fields_or_prefetches:
                if isinstance(f, str):
                    limits[f] = limit
                else:
                    limits[f.prefetch_to] = limit
            return (
                self
                .prefetch_related(*fields_or_prefetches)
                .with_evaluation_callbacks(get_prefetch_limiter(limits))
            )

        function_name = inspect.currentframe().f_code.co_name
        prefetches: List[Prefetch] = []
        for field_or_prefetch in fields_or_prefetches:
            if isinstance(field_or_prefetch, str):
                model = find_model_by_path(self.model, field_or_prefetch)
                related_descriptor = get_relation_from_path(self.model, field_or_prefetch)

                if not (hasattr(related_descriptor, 'rel') and related_descriptor.rel.multiple):
                    raise ValueError(
                        f'"{field_or_prefetch}" is a one-to-one|many-to-one relation. '
                        f'It will always prefetch 0-1 objects, '
                        f'so move it to default "pool_related", "prefetch_related", "select_related" or "select_related_pooled"'
                        f'instead of "{function_name}"'
                    )
                prefetches.append(Prefetch(field_or_prefetch,
                                           queryset=model.objects.distinct(related_descriptor.field.column)))
            else:
                qs = field_or_prefetch.queryset
                related_descriptor = get_relation_from_path(self.model, field_or_prefetch.prefetch_through)
                if qs is None:
                    qs = related_descriptor.field.model.objects.all()
                if qs.query.distinct:
                    raise ValueError(
                        f'{function_name} does not support distinct querysets. '
                        f"Replace {function_name}() with .prefetch_related(Prefetch('field', qs.distinct(...)))"
                    )
                field_or_prefetch.queryset = qs.distinct(related_descriptor.field.column)
                prefetches.append(field_or_prefetch)

        return self.prefetch_related(*prefetches)

    def map_related(self,
                    map_through: Union[str, MapRelatedCall],
                    *mapping_conditions: MapRelatedCondition) -> Self:
        """
        Maps results of a queryset to different lists based on to_atr
        :param map_through:
        :param mapping_conditions:
        """

        if not isinstance(map_through, (str, MapRelatedCall)):
            raise ValueError('source must be either a string or MapRelatedCall')

        if isinstance(map_through, str):
            related_field = self.model._meta.get_field(map_through)
            map_through = MapRelatedCall(qs=related_field.related_model.objects.all(),
                                         group_by_attr=f'{related_field.remote_field.name}_id')
        return (
            self
            .with_evaluation_callbacks(
                get_map_related_callback(map_through, mapping_conditions)
            )
        )

    def prefetch_unrelated(self, *unrelated_prefetches: PrefetchUnrelatedCall) -> Self:
        """
        Use this to prefetch something without direct relation to the current model
        """
        return self.with_evaluation_callbacks(
            *(
                lambda results: map_instances(results, call.qs, call.group_by_attr, call.map_by_attr, call.map_to_attr)
                for call in unrelated_prefetches
            )
        )

    def _fetch_all(self) -> None:
        if self._pool_select_related:
            with RelatedPopulatorMonkeypatch():
                super()._fetch_all()
        else:
            super()._fetch_all()

        self._evaluate_pool_related_calls()

        if not self._eval_callbacks_called:
            self._eval_callbacks_called = True
            for cb in self._evaluation_callbacks:
                processed_results = cb(self._result_cache)
                if processed_results is not None:
                    self._result_cache = processed_results

    def _clone(self) -> Self:
        clone = super()._clone()
        clone._evaluation_callbacks = self._evaluation_callbacks.copy()
        clone._pool_related_calls = self._pool_related_calls.copy()
        clone._pool_select_related = self._pool_select_related
        return clone

    def _evaluate_pool_related_calls(self) -> None:
        if not self._pool_related_done:
            self._pool_related_done = True
            for model, model_relations_to_pull in self._pool_related_calls.items():
                model_relations_to_pull.pool_related_calls.append(
                    PoolRelatedCall(model.objects.all(), model_relations_to_pull.related_fields)
                )
                for pool_related_call in model_relations_to_pull.pool_related_calls:
                    pool_related_call.evaluate(self._result_cache)
