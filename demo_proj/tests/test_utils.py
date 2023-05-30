from django.test import TestCase

from data_models.models import Ride, User, Address, Vehicle
from django_orm_performance_enhancers.utils import (
    get_relation_from_path, get_related_id_from_obj_path, find_model_by_path,
    set_related_obj_to_path_from_pool
)


class UtilsTestCase(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        address1, address2 = Address.objects.bulk_create([
            Address(),
            Address()
        ])
        passenger = User.objects.create(address=address2)
        cls.ride = Ride.objects.create(
            driver=User.objects.create(address=address1),
            passenger=passenger,
            vehicle=Vehicle.objects.create(owner=passenger, parking_address=Address.objects.create()),
            start_point=address1,
            end_point=address2,
        )

    def test_get_obj_from_path_one_level(self):
        self.assertEqual(self.ride.driver, get_relation_from_path(self.ride, 'driver'))

    def test_get_obj_from_path_deep(self):
        self.assertEqual(self.ride.driver.address, get_relation_from_path(self.ride, 'driver__address'))

    def test_get_related_id_from_obj_path_one_level(self):
        self.assertEqual(self.ride.driver_id, get_related_id_from_obj_path(self.ride, 'driver'))

    def test_get_related_id_from_obj_path_deep(self):
        self.assertEqual(self.ride.driver.address_id,
                         get_related_id_from_obj_path(self.ride, 'driver__address'))

    def test_find_model_by_path_one_level(self):
        self.assertIs(User, find_model_by_path(Ride, 'driver'))

    def test_find_model_by_path_deep(self):
        self.assertIs(Address, find_model_by_path(Ride, 'driver__address'))

    def test_set_related_obj_to_path_from_pool(self):
        new_owner = User.objects.create(address=Address.objects.create())
        pool = {new_owner.id: new_owner}

        self.assertNotEqual(self.ride.vehicle.owner, new_owner, 'Owner must be different before setting')
        self.ride.vehicle.owner_id = new_owner.id
        set_related_obj_to_path_from_pool(self.ride, 'vehicle__owner', pool)
        self.assertEqual(self.ride.vehicle.owner, new_owner, 'Owner must be new after setting')
