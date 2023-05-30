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


class Vehicle(models.Model):
    class Makes(models.TextChoices):
        BMW = 'bmw'
        FORD = 'ford'
        TOYOTA = 'toyota'

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='vehicles')
    parking_address = models.ForeignKey(Address, on_delete=models.CASCADE, related_name='parked_vehicles')
    make = models.CharField(max_length=100,
                             choices=Makes.choices,
                             default=Makes.BMW)

    objects = ExtendedQuerySet.as_manager()

    def __repr__(self):
        return f'{self.make}#{self.id} of #{self.owner_id} parked at {self.parking_address_id}'


class Ride(models.Model):
    driver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='driver_rides')
    passenger = models.ForeignKey(User, on_delete=models.CASCADE, related_name='passenger_rides')

    start_point = models.ForeignKey(Address, on_delete=models.CASCADE, related_name='rides_starting_here')
    end_point = models.ForeignKey(Address, on_delete=models.CASCADE, related_name='rides_ending_here')

    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE, related_name='rides')

    objects = ExtendedQuerySet.as_manager()


class Transaction(models.Model):
    class Types(models.TextChoices):
        PAYMENT = 'payment', 'Payment'
        REFUND = 'refund', 'Refund'
        charge = 'charge', 'Charge'

    ride = models.ForeignKey(to=Ride, on_delete=models.CASCADE, related_name='transactions', null=True)
    parent = models.ForeignKey('self',
                               on_delete=models.CASCADE,
                               null=True,
                               related_name='children')
    type = models.CharField(max_length=10, choices=Types.choices, default=Types.PAYMENT)
    user_id = models.PositiveSmallIntegerField(help_text='Intentionally unlinked user_id to test prefetch_unrelated')

    objects = ExtendedQuerySet.as_manager()
