import random
from collections import defaultdict
from typing import TypeVar, DefaultDict, Type, List, Set
from unittest import mock

from django.db.models import Model, Count, Prefetch, Q
from django.test import TestCase

from data_models.models import Ride, User, Vehicle, Address, Transaction
from django_orm_performance_enhancers.querysets import PoolRelatedCall, PrefetchUnrelatedCall
from django_orm_performance_enhancers.evaluation_callbacks import MapRelatedCall, MapRelatedCondition
from django_orm_performance_enhancers.utils import get_relation_from_path

TModel = TypeVar('TModel', bound=Model)
PoolType = DefaultDict[int, List[TModel]]


class EvaluationCallbackTestCase(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        super().setUpTestData()
        cls.users = User.objects.bulk_create([
            User(address=address)
            for address in Address.objects.bulk_create([Address() for _ in range(5)])
        ])

    def setUp(self):
        self.callback_no_return = mock.MagicMock(return_value=None)

    @staticmethod
    def _get_qs():
        return User.objects.select_related('address')

    def test_no_extra_queries(self):
        with self.assertNumQueries(1):
            list(self._get_qs().with_evaluation_callbacks(self.callback_no_return))

    def test_callback_with_no_return_doesnt_empty_results(self):
        self.assertEqual(
            list(self._get_qs().with_evaluation_callbacks(self.callback_no_return)),
            list(self._get_qs()),
            'Results must be the same if callback does not return anything'
        )
        self.callback_no_return.assert_called_once()

    def test_callback_with_return_modified_qs_results(self):
        return_value = self.users[:2]
        callback_with_return = mock.MagicMock(return_value=return_value)
        no_callback_results = list(self._get_qs())
        with_callback_results = list(self._get_qs().with_evaluation_callbacks(callback_with_return))
        callback_with_return.assert_called_once_with(no_callback_results)
        self.assertEqual(
            with_callback_results,
            return_value
        )


class ObjectPoolingTestCase(TestCase):
    addresses: List[Address]
    users: List[User]
    vehicles: List[Vehicle]
    rides: List[Ride]

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.addresses = Address.objects.bulk_create([Address() for _ in range(5)])
        cls.users = User.objects.bulk_create([
            User(address=random.choice(cls.addresses))
            for _ in range(10)
        ])
        users_set = set(cls.users)
        cls.vehicles = Vehicle.objects.bulk_create([
            Vehicle(owner=random.choice(cls.users), parking_address=Address.objects.create())
            for _ in range(3)
        ])

        rides_to_save = []
        address_set = set(cls.addresses)
        for _ in range(20):
            driver = random.choice(cls.users)
            start_point = random.choice(cls.addresses)
            rides_to_save.append(
                Ride(driver=driver,
                     vehicle=random.choice(cls.vehicles),
                     passenger=random.choice(list(users_set - {driver})),
                     start_point=start_point,
                     end_point=random.choice(list(address_set - {start_point}))),
            )
        cls.rides = Ride.objects.bulk_create(rides_to_save)

    def test_simple_pool_related(self):
        prefetched = list(Ride.objects.select_related('driver'))
        with self.assertNumQueries(2):
            pooled = list(Ride.objects.pool_related('driver'))

        self._check_results_correctness(prefetched, pooled, 'driver')

        drivers_objects_lists_by_id = defaultdict(list)
        for ride in pooled:
            drivers_objects_lists_by_id[ride.driver_id].append(ride.driver)

        for driver_objects_list in drivers_objects_lists_by_id.values():
            self._check_reference_equality(driver_objects_list)

    def test_complex_pool_related(self):
        normal = list(
            Ride
            .objects
            .prefetch_related('driver__address',
                              'passenger__address',
                              'start_point',
                              'end_point',
                              'vehicle__owner__address')
        )
        with self.assertNumQueries(3):
            pooled = list(
                Ride
                .objects
                .select_related('vehicle')
                .pool_related('driver',
                              'passenger',
                              'vehicle__owner')
                .pool_related('driver__address',
                              'passenger__address',
                              'start_point',
                              'end_point',
                              'vehicle__owner__address')
            )

        self._check_results_correctness(
            normal,
            pooled,
            'driver',
            'passenger',
            'vehicle__owner',
            'driver__address',
            'passenger__address',
            'start_point',
            'end_point'
        )

        user_pool = self._get_related_objs_list_pool(
            pooled,
            User,
            'driver',
            'passenger',
            'vehicle__owner',
        )
        address_pool = self._get_related_objs_list_pool(
            pooled,
            Address,
            'driver__address',
            'passenger__address',
            'start_point',
            'end_point'
        )
        list(map(self._check_reference_equality, user_pool.values()))
        list(map(self._check_reference_equality, address_pool.values()))

        self.assertEqual(self._get_related_objs_set(normal,
                                                    User,
                                                    'driver',
                                                    'passenger',
                                                    'vehicle__owner'),
                         self._get_related_objs_set(pooled,
                                                    User,
                                                    'driver',
                                                    'passenger',
                                                    'vehicle__owner'),
                         'Unique users in normal and pooled results are not the same')
        self.assertEqual(self._get_related_objs_set(normal,
                                                    Address,
                                                    'driver__address',
                                                    'passenger__address',
                                                    'start_point',
                                                    'end_point'),
                         self._get_related_objs_set(pooled,
                                                    Address,
                                                    'driver__address',
                                                    'passenger__address',
                                                    'start_point',
                                                    'end_point'),
                         'Unique addresses in normal and pooled results are not the same')

    def test_mixed_pool_related(self):
        normal = list(
            Ride
            .objects
            .prefetch_related('driver', 'passenger', 'vehicle__owner__address')
        )
        with self.assertNumQueries(3):
            pooled = list(
                Ride
                .objects
                .select_related('vehicle')
                .pool_related('driver',
                              'passenger',
                              # pull owner with address for vehicle pulled in .select_related('vehicle')
                              PoolRelatedCall(User.objects.select_related('address'), ['vehicle__owner']))
            )

        # pooling worked for driver and passenger
        user_pool = self._get_related_objs_list_pool(
            pooled,
            User,
            'driver',
            'passenger',
        )
        list(map(self._check_reference_equality, user_pool.values()))

        # check pooling worked for vehicle__owner
        user_pool = self._get_related_objs_list_pool(
            pooled,
            User,
            'vehicle__owner',
        )
        list(map(self._check_reference_equality, user_pool.values()))

        with self.assertRaises(AssertionError):
            # check pooling wasn't done for vehicle__owner
            user_pool = self._get_related_objs_list_pool(
                pooled,
                User,
                'driver',
                'passenger',
                'vehicle__owner',
            )
            list(map(self._check_reference_equality, user_pool.values()))

        self.assertEqual(self._get_related_objs_set(normal,
                                                    User,
                                                    'driver',
                                                    'passenger',
                                                    'vehicle__owner'),
                         self._get_related_objs_set(pooled,
                                                    User,
                                                    'driver',
                                                    'passenger',
                                                    'vehicle__owner'),
                         'Unique users in normal and pooled results are not the same')

    def test_select_related_pooled(self):
        normal = list(Ride.objects.select_related('driver__address'))
        with self.assertNumQueries(1):
            pooled = list(Ride.objects.select_related_pooled('driver__address'))
        self._check_results_correctness(normal, pooled, 'driver__address')
        self._check_results_correctness(normal, pooled, 'driver')

        list(map(self._check_reference_equality,
                 self._get_related_objs_list_pool(pooled, User, 'driver').values()))
        list(map(self._check_reference_equality,
                 self._get_related_objs_list_pool(pooled, Address, 'driver__address').values()))

    def test_prefetch_related_with_limit_string(self):
        with self.assertNumQueries(2):
            vehicles_with_one_ride_only = list(
                Vehicle
                .objects
                .prefetch_related_with_limit('rides')
            )

        self._check_prefetch_related_one_rides(vehicles_with_one_ride_only)

    def test_prefetch_related_with_limit_with_simple_prefetch_obj(self):
        with self.assertNumQueries(2):
            vehicles_with_one_ride_only = list(
                Vehicle
                .objects
                .prefetch_related_with_limit(Prefetch('rides'))
            )

        self._check_prefetch_related_one_rides(vehicles_with_one_ride_only)

    def test_prefetch_related_with_limit_with_complex_prefetch_obj(self):
        with self.assertNumQueries(2):
            vehicles_with_one_ride_only = list(
                Vehicle
                .objects
                .prefetch_related_with_limit(Prefetch('rides',
                                               Ride
                                               .objects
                                               .select_related('driver')))
            )
        self._check_prefetch_related_one_rides(vehicles_with_one_ride_only)

    def test_prefetch_related_with_limit_1_via_python(self):
        with self.assertNumQueries(2):
            vehicles_with_one_ride_only = list(
                Vehicle
                .objects
                .prefetch_related_with_limit('rides', limit=1)
            )
        self._check_prefetch_related_one_rides(vehicles_with_one_ride_only)

    def test_prefetch_related_with_limit_3_via_python(self):
        with self.assertNumQueries(2):
            vehicles_with_one_ride_only = list(
                Vehicle
                .objects
                .prefetch_related_with_limit('rides', limit=3)
            )
        self._check_prefetch_related_one_rides(vehicles_with_one_ride_only, 3)

    def test_prefetch_related_with_limit_fails_with_many_to_one(self):
        with self.assertRaises(ValueError):
            list(Vehicle.objects.prefetch_related_with_limit('owner'))

    def test_prefetch_related_with_limit_fails_with_one_to_one(self):
        with self.assertRaises(ValueError):
            list(Vehicle.objects.prefetch_related_with_limit('parking_address'))

    def test_prefetch_related_with_limit_fails_on_simple_distinct_qs(self):
        with self.assertRaises(ValueError):
            list(Vehicle.objects.prefetch_related_with_limit(Prefetch('rides', Ride.objects.distinct())))

    def test_prefetch_related_with_limit_fails_on_complex_distinct_qs(self):
        with self.assertRaises(ValueError):
            list(Vehicle.objects.prefetch_related_with_limit(Prefetch('rides', Ride.objects.distinct('id'))))

    def _check_prefetch_related_one_rides(self, vehicles_with_one_ride_only: List[Vehicle], limit: int = 1):
        for vehicle in vehicles_with_one_ride_only:
            with self.assertNumQueries(0, msg='Prefetch objects cache didnt work'):
                self.assertLessEqual(len(vehicle.rides.all()), limit, 'Limit on rides did not work')

        self.assertTrue(
            Vehicle.objects.annotate(rides_count=Count('rides')).filter(rides_count__gt=limit).exists(),
            f'There are no vehicles with more than {limit} rides'
        )

    def _check_results_correctness(self, regular_results: List[TModel], pooled_results: List[TModel], *pooling_paths: str):
        for regular, pooled in zip(regular_results, pooled_results):
            for path in pooling_paths:
                self.assertEqual(get_relation_from_path(regular, path), get_relation_from_path(pooled, path),
                                 'Regular and pooled objects are not equal')

    def _check_reference_equality(self, objs: List[TModel]):
        for obj in objs[1:]:
            self.assertIs(objs[0], obj, 'Objects from the pool are not the same by reference')

    @staticmethod
    def _get_related_objs_list_pool(objs: List[Model], output_type: Type[TModel], *paths) -> PoolType[TModel]:
        """
        :param objs: iterable of model instances to collect from
        :param paths: paths to collect from into a pool
        :returns dict of lists by id, of model instances with same id(to check for reference equality later)
        """
        objects_pool: PoolType[output_type] = defaultdict(list)
        for obj in objs:
            for path in paths:
                related_obj = get_relation_from_path(obj, path)
                objects_pool[related_obj.id].append(related_obj)
        return objects_pool

    @staticmethod
    def _get_related_objs_set(objs: list, output_type: Type[TModel], *paths) -> Set[TModel]:
        """
        :param objs: iterable of model instances to collect from
        :param paths: paths to collect from into a pool
        """
        objects_set: Set[output_type] = set()
        for obj in objs:
            for path in paths:
                objects_set.add(get_relation_from_path(obj, path))
        return objects_set


class MapRelatedTestCase(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.user = User.objects.create(address=Address.objects.create())
        cls.bwm_vehicles = Vehicle.objects.bulk_create([
            Vehicle(owner=cls.user, make=Vehicle.Makes.BMW, parking_address=cls.user.address)
            for _ in range(3)
        ])
        cls.toyota_vehicles = Vehicle.objects.bulk_create([
            Vehicle(owner=cls.user, make=Vehicle.Makes.TOYOTA, parking_address=cls.user.address)
            for _ in range(4)
        ])
        cls.ford_vehicles = Vehicle.objects.bulk_create([
            Vehicle(owner=cls.user, make=Vehicle.Makes.FORD, parking_address=cls.user.address)
            for _ in range(5)
        ])

    def test_map_related_simple(self):
        with self.assertNumQueries(2):
            user = (
                User
                .objects
                .map_related(
                    'vehicles',
                    MapRelatedCondition(Q(make=Vehicle.Makes.BMW), 'bmw_vehicles'),
                    MapRelatedCondition(Q(make=Vehicle.Makes.TOYOTA), 'toyota_vehicles'),
                    MapRelatedCondition(Q(make=Vehicle.Makes.FORD), 'ford_vehicles'),
                )
                [0]
            )

        self.assertEqual(len(user.bmw_vehicles), len(self.bwm_vehicles))
        self.assertEqual(len(user.toyota_vehicles), len(self.toyota_vehicles))
        self.assertEqual(len(user.ford_vehicles), len(self.ford_vehicles))

    def test_map_related_simple_verbose(self):
        with self.assertNumQueries(2):
            user = (
                User
                .objects
                .map_related(
                    MapRelatedCall(Vehicle.objects.all(), 'owner_id'),
                    MapRelatedCondition(Q(make=Vehicle.Makes.BMW), 'bmw_vehicles'),
                    MapRelatedCondition(Q(make=Vehicle.Makes.TOYOTA), 'toyota_vehicles'),
                    MapRelatedCondition(Q(make=Vehicle.Makes.FORD), 'ford_vehicles'),
                )
                [0]
            )

        self.assertEqual(len(user.bmw_vehicles), len(self.bwm_vehicles))
        self.assertEqual(len(user.toyota_vehicles), len(self.toyota_vehicles))
        self.assertEqual(len(user.ford_vehicles), len(self.ford_vehicles))


class PrefetchUnrelatedTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user1 = User.objects.create(address=Address.objects.create())
        cls.user2 = User.objects.create(address=Address.objects.create())
        cls.vehicles = cls.user2.vehicles.bulk_create([
            Vehicle(parking_address=cls.user1.address, owner=cls.user2),
            Vehicle(parking_address=cls.user1.address, owner=cls.user2)
        ])
        cls.transactions = Transaction.objects.bulk_create([
            Transaction(user_id=cls.user1.id),
            Transaction(user_id=cls.user1.id),
            Transaction(user_id=cls.user1.id),
        ])

    def test_prefetch_unrelated_simple_remapping(self):
        with self.assertNumQueries(2):
            users_with_vehicles_parked_on_their_premises = (
                User
                .objects
                .prefetch_unrelated(
                    PrefetchUnrelatedCall(
                        Vehicle.objects.all(),
                        'parking_address_id',
                        'address_id',
                        'vehicles_parked_on_user_premises'
                    )
                )
            )
            self.assertSequenceEqual(
                users_with_vehicles_parked_on_their_premises.get(id=self.user1.id).vehicles_parked_on_user_premises,
                self.vehicles
            )


    def test_completely_unrelated_prefetch(self):
        with self.assertNumQueries(2):
            users_with_transactions = (
                User
                .objects
                .prefetch_unrelated(
                    PrefetchUnrelatedCall(
                        Transaction.objects.all(),
                        'user_id',
                        'id',
                        'unrelated_transactions'
                    )
                )
            )
            self.assertSequenceEqual(
                users_with_transactions.get(id=self.user1.id).unrelated_transactions,
                self.transactions
            )


