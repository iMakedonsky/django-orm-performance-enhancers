from typing import Optional, Callable, TypeVar, Generic

from django.db.models import Model, QuerySet

TProperty = TypeVar('TProperty')
TModel = TypeVar('TModel', bound=Model, covariant=True)

class PrefetchedProperty(Generic[TModel, TProperty]):
    """
    a descriptor class to be used on django models as following
    class MyModel(models.Model):
        ...
        my_property = PrefetchedProperty(models.Prefetch(),
                                         queryset_method_name='with_my_property',
                                         cache_variable_name='_my_property_cache')
    adds a method 'with_my_property' to the model queryset, which uses the Prefetch object and maps
    the results to the cache_variable_name
    """
    def __init__(self,
                 queryset_method: Callable[[QuerySet[TModel]], QuerySet[TModel]],
                 single_instance_getter: Callable[[TModel], TProperty],
                 cache_attr_name: Optional[str] = None):
        self.queryset_method = queryset_method
        self.single_instance_getter = single_instance_getter
        self.cache_attr_name = cache_attr_name

    def __set_name__(self, owner: Model, name: str):
        self.cache_attr_name = self.cache_attr_name or f'_{name}'

    def __get__(self, instance, owner: type) -> TProperty:
        if not hasattr(instance, self.cache_attr_name):
            setattr(instance, self.cache_attr_name, self.single_instance_getter(instance))
        return getattr(instance, self.cache_attr_name, None)

    def __set__(self, instance: TModel, value: TProperty):
        setattr(instance, self.cache_attr_name, value)

    def __delete__(self, instance: TModel):
        delattr(instance, self.cache_attr_name)

