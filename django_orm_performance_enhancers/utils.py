from collections import defaultdict
from typing import Union, Type, Dict, Sequence, TypeVar

from django.db.models import Model, Manager, QuerySet


ModelIdType = Union[str, int]
TModel = TypeVar('TModel', bound=Model)


def find_model_by_path(base_model: Type[Model], path: str) -> Type[Model]:
    """
    Given a django-orm path like 'user__profile__address',
    return the address model class.
    """
    model = base_model
    for field in path.split('__'):
        model = model._meta.get_field(field).related_model
    return model


def get_related_id_from_obj_path(obj: Model, path: str) -> ModelIdType:
    """
    Given a django-orm path like 'user__profile__address',
    return the address id.
    """
    parts = path.split('__')
    for field in parts[:-1]:
        obj = getattr(obj, field)
    return getattr(obj, f'{parts[-1]}_id')


def set_related_obj_to_path_from_pool(obj: Model, path: str, pool: Dict[ModelIdType, Model]) -> None:
    """
    Given a django-orm path like 'user__profile__address',
    set the address object to the user object.
    """
    parts = path.split('__')
    for field in parts[:-1]:
        obj = getattr(obj, field)
    setattr(obj, parts[-1], pool[getattr(obj, f'{parts[-1]}_id')])


def get_relation_from_path(parent: Model, path: str) -> Union[Model, Manager]:
    """
    Given a parent User and a django-orm path like 'user__profile__address',
    return the address object/descriptor
    """
    parts = path.split('__')
    for field in parts:
        parent = getattr(parent, field)
    return parent


def map_instances(to_instances: Sequence[TModel],
                  from_qs: QuerySet,
                  group_by_attr: str,
                  map_by_attr: str,
                  map_to_attr: str) -> None:

    pull_for_ids = set()
    parents_map = defaultdict(list)
    for instance in to_instances:
        map_by_attr_value = getattr(instance, map_by_attr)
        pull_for_ids.add(map_by_attr_value)
        parents_map[map_by_attr_value].append(instance)
        setattr(instance, map_to_attr, [])

    for related_result in from_qs.filter(**{f'{group_by_attr}__in': pull_for_ids}):
        for parent in parents_map[getattr(related_result, group_by_attr)]:
            getattr(parent, map_to_attr).append(related_result)
