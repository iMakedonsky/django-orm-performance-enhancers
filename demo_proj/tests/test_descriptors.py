from django.test import TestCase

from data_models.models import User, Address, Vehicle


class TestPrefetchedPropertyTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create(address=Address.objects.create())
        cls.vehicles_parked_on_the_user_address = [
            Vehicle.objects.create(parking_address=cls.user.address,
                                   make=Vehicle.Makes.BMW,
                                   owner=cls.user),
            Vehicle.objects.create(parking_address=cls.user.address,
                                   make=Vehicle.Makes.FORD,
                                   owner=User.objects.create(address=Address.objects.create())),
        ]
        cls.vehicles_parked_elsewhere = [
            Vehicle.objects.create(parking_address=Address.objects.create(),
                                   make=Vehicle.Makes.TOYOTA,
                                   owner=User.objects.create(address=Address.objects.create())),
            Vehicle.objects.create(parking_address=Address.objects.create(),
                                   make=Vehicle.Makes.BMW,
                                   owner=User.objects.create(address=Address.objects.create())),
        ]
        driver = User.objects.create(address=Address.objects.create())
        cls.user.passenger_rides.create(vehicle=cls.vehicles_parked_elsewhere[0],
                                        driver=driver,
                                        start_point=driver.address,
                                        end_point=driver.address)
        cls.user.passenger_rides.create(vehicle=cls.vehicles_parked_elsewhere[0],
                                        driver=driver,
                                        start_point=driver.address,
                                        end_point=driver.address)
        cls.user.passenger_rides.create(vehicle=cls.vehicles_parked_elsewhere[1],
                                        driver=driver,
                                        start_point=driver.address,
                                        end_point=driver.address)
        cls.user.passenger_rides.create(vehicle=cls.vehicles_parked_elsewhere[1],
                                        driver=driver,
                                        start_point=driver.address,
                                        end_point=driver.address)

    def test_prefetched_property_single_instance_getter(self):
        with self.assertNumQueries(1):
            self.assertSequenceEqual(
                self.user.vehicles_parked_on_user_address,
                self.vehicles_parked_on_the_user_address
            )

    def test_prefetched_property_through_query_set_method_cache_setter(self):
        with self.assertNumQueries(2):
            self.assertSequenceEqual(
                (
                    User
                    .objects
                    .with_vehicles_parked_on_user_address()
                    .get(id=self.user.id)
                    .vehicles_parked_on_user_address
                ),
                self.vehicles_parked_on_the_user_address
            )

    def test_prefetched_property_nonstandard_cache_attr_name_single(self):
        with self.assertNumQueries(1):
            self.assertEqual(
                self.user.amount_passenger_rides,
                4
            )

    def test_prefetched_property_nonstandard_cache_attr_name_through_query_set_method(self):
        with self.assertNumQueries(1):  # only 1 query because we use count annotation
            self.assertEqual(
                User.objects.with_amount_passenger_rides().get(id=self.user.id).amount_passenger_rides,
                4
            )
