from dataclasses import dataclass
from typing import Callable, TypeVar, Sequence, Generic, Union, Dict

from django.db.models import Model, QuerySet, Q, Case, CharField, When, Value

from django_orm_performance_enhancers.utils import get_relation_from_path

TModel = TypeVar('TModel', bound=Model)

EvaluationCallbackType = Callable[[Sequence[TModel]], Union[Sequence[TModel], None]]


def get_prefetch_limiter(field_limits_map: Dict[str, int]) -> EvaluationCallbackType:
    """
    Without CTE, it's impossible to limit the number of prefetch_related results
    via SQL, so we do it in python.

    :param field_limits_map:  {'relation_path': limit}, e.g. {'user': 1}
    Example:
    >>> School
    >>> .objects
    >>> .prefetch_related('students')
    >>> .with_evaluation_callback(get_prefetch_limiter({'students': 1}))
    """
    def limit_callback(results: Sequence[TModel]) -> None:
        for obj in results:
            for field, limit in field_limits_map.items():
                # calling .all() returns qs._result_cache
                related_obj_list = get_relation_from_path(obj, field).all()
                if isinstance(getattr(obj, field), list):
                    # if prefetched with to_attr
                    setattr(obj, field, related_obj_list[:limit])
                else:
                    # if setting to django reverse/forward descriptor/manager
                    obj._prefetched_objects_cache[field] = related_obj_list[:limit]
    return limit_callback


@dataclass
class MapRelatedCall(Generic[TModel]):
    """
    For example:
    Author: Books

    Author
    .objects
    .map_related(
        MapRelatedCall(
            qs=Book.objects.all(),
            child_field_name='author_id',
            parent_field_name='id'
        )
        MapRelatedCondition(Q(genre='fantasy'), 'fantasy_books'),
        MapRelatedCondition(Q(genre='sci-fi'), 'sci_fi_books'),
        MapRelatedCondition(Q(genre='horror'), 'horror_books'),
    )
    """
    qs: QuerySet[TModel]
    group_by_attr: str
    map_by_attr: str = 'id'


@dataclass
class MapRelatedCondition:
    case_q: Q
    to_attr: str


def get_map_related_callback(map_through: MapRelatedCall, mapping_conditions: Sequence[MapRelatedCondition]) -> EvaluationCallbackType:
    conditions = []
    for condition in mapping_conditions:
        conditions.append(When(condition.case_q, then=Value(condition.to_attr)))

    def map_related_callback(results: Sequence[TModel]) -> None:
        if not results:
            return

        fetch_for_ids = set()
        parents_map = {}
        for result in results:
            link_attr_value = getattr(result, map_through.map_by_attr)
            parents_map[link_attr_value] = result
            fetch_for_ids.add(link_attr_value)
            for p in mapping_conditions:
                setattr(result, p.to_attr, [])

        column_name = '_' + '_'.join([p.to_attr for p in mapping_conditions])
        for related_child in (
                map_through.qs.annotate(
                    **{column_name: Case(*conditions, output_field=CharField())}
                ).filter(**{f'{map_through.group_by_attr}__in': fetch_for_ids})
        ):
            parent = parents_map[getattr(related_child, map_through.group_by_attr)]
            destination_list_attr_name = getattr(related_child, column_name)
            getattr(parent, destination_list_attr_name).append(related_child)

    return map_related_callback
