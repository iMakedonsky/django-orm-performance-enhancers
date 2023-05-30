# django-orm-performance-enhancers (DOPEs)

[![PyPI - Version](https://img.shields.io/pypi/v/django-orm-performance-enhancers.svg)](https://pypi.org/project/django-orm-performance-enhancers)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/django-orm-performance-enhancers.svg)](https://pypi.org/project/django-orm-performance-enhancers)

-----

**Table of Contents**

- [Installation](#installation)
- [Example Models](#example-models)
- [ExtendedQuerySet](#extendedqueryset)
  - [with_evaluation_callbacks](#withevaluationcallbacks)
  - [pool_related](#poolrelated)
  - [select_related_pooled](#selectrelatedpooled)
  - [prefetch_related_with_limit](#prefetchrelatedwithlimit)
  - [map_related](#maprelated)
  - [prefetch_unrelated](#prefetchunrelated)
- [PrefetchedProperty](#prefetchedproperty)


## Installation

```console
pip install django-orm-performance-enhancers
```

## Example Models
Please see `demo_project/data_models/models.py` for the models used in the examples below.
For extra samples beyond what's shown in the README, see the tests.


## ExtendedQuerySet
Usage:
```python
from django.db import models
from django_orm_performance_enhancers import ExtendedQuerySet

class MyModelQuerySet(ExtendedQuerySet):
    pass

class MyModel(models.Model):
    objects = MyModelQuerySet.as_manager()
    # or objects = ExtendedQuerySet.as_manager()
```

### with_evaluation_callbacks
As the name suggests, adds callbacks to be evaluated when the queryset is evaluated.
Think of it as a python-based `.annotate` method.

API:

`with_evaluation_callbacks(self, *evaluation_callbacks: EvaluationCallbackType)`

`EvaluationCallbackType = Callable[[Sequence[TModel]], Union[Sequence[TModel], None]]`

Useful for:
- creating custom annotations
- transforming/processing data after evaluation
- prefetching related objects which is tricky or not doable in ORM way
- filtering prefetches in a way not achievable by ORM
- prefetching from tables which don't have a direct relation to current model
- re-using data fetched elsewhere in the queryset
- doing custom joins, which are not possible in ORM way

See a sample:
```python
from data_models.models import User, Vehicle

def prefetch_vehicles_parked_on_user_address(results: list[User]):
    address_ids = {user.address_id for user in results}
    for user in results:
        vehicles_by_address_id = {
            vehicle.address_id: vehicle 
           for vehicle in Vehicle.objects.filter(address_id__in=address_ids)
        }
        user.vehicles_parked_on_user_address = vehicles_by_address_id.get(user.address_id, [])

class UserQuerySet:
    def with_vehicles_parked_on_user_address(self):
        return self.with_evaluation_callbacks(prefetch_vehicles_parked_on_user_address)
    
qs = (
    User
    .objects
    .with_vehicles_parked_on_user_address()  # no evaluation
)
qs = qs.annotate(...) # no evaluation

[x.vehicles_parked_on_user_address for x in qs]  # evaluated in a single query to Vehicles parked on the user address.
```

### pool_related
A drop-in replacement for `prefetch_related` which uses a pool of prefetched results.

This has 3 benefits:
 - reduces CPU and memory usage while fetching particularly large datasets by re-using instances of models with the same id
By default, django creates a new instance of a model for each row even if they have the same id. Here related objs are shared
by reference instead.
**There's a catch**: if you modify a shared object, it will get modified everywhere. 
This might or might not be what you wanted.
- reduces the number of queries by combining multiple prefetch_related targets into one query
- helps saving time on joining the same table multiple times via `select_related` and re-using the same annotations, 
which might or might not increase performance. Always benchmark when in doubt.

<details>
<summary>⤵️Reducing the number of queries:</summary>

```python
from data_models.models import User

regular_results = list(
    User
    .objects
    .select_related('address') # Query1: User + Address
                      # Query2: rides_starting_here
                      # Query3: rides_ending_here
                      # Query4: transactions for rides_starting_here
                      # Query5: transactions for rides_ending_here
    .prefetch_related('address__rides_starting_here__transactions',
                      'address__rides_ending_here__transactions') 
)
first_ride_starting_at_user_address = regular_results[0].address.rides_starting_here.all()[0]
first_ride_ending_at_user_address = regular_results[0].address.rides_ending_here.all()[0]
first_ride_starting_at_user_address.id == first_ride_ending_at_user_address.id  # True
first_ride_starting_at_user_address is first_ride_ending_at_user_address  # False


pooled_results = list(
    User
    .objects
    .select_related('address') # Query1: User + address
    .pool_related('address__rides_starting_here',
                  'address__rides_ending_here') # Query2: all rides
    .pool_related('address__rides_starting_here__transactions',
                  'address_rides_ending_here__transactions') # Query3: all transactions
)
first_ride_starting_at_user_address = pooled_results[0].address.rides_starting_here.all()[0]
first_ride_ending_at_user_address = pooled_results[0].address.rides_ending_here.all()[0]
first_ride_starting_at_user_address.id == first_ride_ending_at_user_address.id  # True
first_ride_starting_at_user_address is first_ride_ending_at_user_address  # True
```
</details>


### select_related_pooled
A drop-in replacement for `select_related` which re-uses model instances with the same id.
By default, django duplicates instances of models with the same id.

<details>
<summary>⤵️Sharing by reference:</summary>

```python
from data_models.models import User

regular_results = list(
    User
    .objects
    .select_related('address')
)
regular_results[0].address.id == regular_results[1].address.id  # True
regular_results[0].address is regular_results[1].address  # False


pooled_results = list(
    User
    .objects
    .select_related_pooled('address') # Query1: User + address
)
regular_results[0].address.id == regular_results[1].address.id  # True
regular_results[0].address is regular_results[1].address  # True
```
</details>

### prefetch_related_with_limit

if `limits` is not provided, assumes LIMIT 1 for all fields and uses DISTINCT ON to get only one result.
If `limits` is provided, manages limiting in python to achieve necessary result, 
because it's not trivial to do limit 2 in SQL without access to `SELECT * from ...` in ORM


API:

```
prefetch_related_with_limit(
    self,
    *fields_or_prefetches: Union[str, Prefetch],
    limit: Optional[int] = None
)
```

### map_related
Lets you batch-load related objects, then sort them to different attributes on the parent object 
based on SQL Case-When statements.
API:
```
map_related(
    self, 
    map_through: Union[str, MapRelatedCall],
    *mapping_conditions: MapRelatedCondition
)

@dataclass
class MapRelatedCondition:
    case_q: Q
    to_attr: str
```
<details>
<summary>⤵️Mapping vehicles by make:</summary>

```python
from data_models.models import User, Vehicle
from django.db.models import Q, Prefetch
from django_orm_performance_enhancers.evaluation_callbacks import MapRelatedCondition


# regular django-orm way
(
    User
    .objects
    .prefetch_related(
       # Query1:
       Prefetch('vehicles', 
                Vehicle.objects.filter(make=Vehicle.Makes.BMW), 
                to_attr='bmw_vehicles'),
       # Query2:
       Prefetch('vehicles',
                Vehicle.objects.filter(make=Vehicle.Makes.TOYOTA),
                to_attr='toyota_vehicles'),
       # Query3:
       Prefetch('vehicles', 
                Vehicle.objects.filter(make=Vehicle.Makes.FORD),
                to_attr='ford_vehicles'),
    )
)


users_with_grouped_vehicles = (
    User
    .objects
    .map_related(
        'vehicles',  # One SQL query to fetch all vehicles
        MapRelatedCondition(Q(make=Vehicle.Makes.BMW), 'bmw_vehicles'),
        MapRelatedCondition(Q(make=Vehicle.Makes.TOYOTA), 'toyota_vehicles'),
        MapRelatedCondition(Q(make=Vehicle.Makes.FORD), 'ford_vehicles'),
    )
)
assert users_with_grouped_vehicles[0].bmw_vehicles[0].make == Vehicle.Makes.BMW
assert users_with_grouped_vehicles[0].toyota_vehicles[0].make == Vehicle.Makes.TOYOTA
assert users_with_grouped_vehicles[0].ford_vehicles[0].make == Vehicle.Makes.FORD
```
</details>

<details>
<summary>⤵️Popular author-book example:</summary>

```python
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
```
</details>


### prefetch_unrelated
Lets you prefetch something with a `to_attr` without direct relation to the parent.

API:
```python
prefetch_unrelated(self, *unrelated_prefetches: PrefetchUnrelatedCall)

@dataclass
class PrefetchUnrelatedCall:
    qs: QuerySetType
    group_by_attr: str
    map_by_attr: str
    map_to_attr: str
```


Fills these usecases:
 - `Prefetch('some__relation__many_levels__deep', to_attr='some_attr_on_first_level')`
 - `Prefetch('...no relation to parent...', to_attr='some_attr_on_parent')`

API:
`prefetch_unrelated(self, *unrelated_prefetches: PrefetchUnrelatedCall)`

<details>
<summary>⤵️Prefetching unrelated objects:</summary>

```python
from data_models.models import User, Transaction
from django_orm_performance_enhancers.querysets import PrefetchUnrelatedCall


users_with_transactions = (
   User
   .objects
   .prefetch_unrelated(
      PrefetchUnrelatedCall(
         # Transaction doesn't have any relation to user, just integer user_id column
         Transaction.objects.all(), 
         'user_id',
         'id',
         'unrelated_transactions'
      )
   )
)
assert users_with_transactions[0].unrelated_transactions[0].user_id == users_with_transactions[0].id
```
</details>

### PrefetchedProperty
Lets you create an easily re-usable attribute to hold either query_set cache of an annotation,
or compute that annotation on the fly.

```python
from typing_extensions import Self
from django.db import models
from django_orm_performance_enhancers.descriptors import PrefetchedProperty
from django_orm_performance_enhancers.querysets import ExtendedQuerySet, PrefetchUnrelatedCall


class Address(models.Model):
    objects = ExtendedQuerySet.as_manager()



class UserQuerySet(ExtendedQuerySet):
    def with_vehicles_parked_on_user_address(self) -> Self:
        # use prefetch_unrelated to assign prefetched objects to user, not to address
        return self.prefetch_unrelated(
            PrefetchUnrelatedCall(
                qs=Vehicle.objects.all(),
                group_by_attr='parking_address_id',
                map_by_attr='address_id',
                map_to_attr='vehicles_parked_on_user_address'  # map to the PrefetchedProperty
            )
        )

    def with_amount_passenger_rides(self) -> Self:
        return self.annotate(pass_rides_cnt=models.Count('passenger_rides'))

class User(models.Model):
    address = models.ForeignKey(Address, on_delete=models.CASCADE, related_name='users')

    vehicles_parked_on_user_address = PrefetchedProperty(
        queryset_method=UserQuerySet.with_vehicles_parked_on_user_address,
        single_instance_getter=lambda user: Vehicle.objects.filter(parking_address_id=user.address_id)
    )

    amount_passenger_rides = PrefetchedProperty(
        queryset_method=UserQuerySet.with_amount_passenger_rides,
        single_instance_getter=lambda user: user.passenger_rides.count(),
        cache_attr_name='pass_rides_cnt'  # use custom attr name from queryset method
    )
    objects = UserQuerySet.as_manager()

       # 2 SQL queries                                # 1 SQL query
assert User.objects.first().amount_passenger_rides == User.objects.with_amount_passenger_rides().first().amount_passenger_rides
```

## License

`django-orm-performance-enhancers` is distributed under the terms of the [MIT](https://spdx.org/licenses/MIT.html) license.
