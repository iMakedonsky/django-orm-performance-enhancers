from functools import wraps

from django.db.models.query import RelatedPopulator


original_populate = RelatedPopulator.populate
original_init = RelatedPopulator.__init__


@wraps(original_init)
def init_with_cache(self, *args, **kwargs):
    original_init(self, *args, **kwargs)
    self._select_related_cache = {}


def caching_populate(self, row, from_obj):
    """
    modified Django 4.1.7 version of RelatedPopulator.populate
    Keeps a cache of already created objects to avoid creating the same object multiple times
    """
    if self.reorder_for_init:
        obj_data = self.reorder_for_init(row)
    else:
        obj_data = row[self.cols_start: self.cols_end]
    obj_pk = obj_data[self.pk_idx]
    if obj_pk is None:
        obj = None
    # NEW CODE START HERE
    elif obj_pk in self._select_related_cache:
        obj = self._select_related_cache[obj_pk]
    # NEW CODE END HERE
    else:
        obj = self.model_cls.from_db(self.db, self.init_list, obj_data)
        for rel_iter in self.related_populators:
            rel_iter.populate(row, obj)
        self._select_related_cache[obj_pk] = obj
    self.local_setter(from_obj, obj)
    if obj is not None:
        self.remote_setter(obj, from_obj)


class RelatedPopulatorMonkeypatch:
    """
    Since django's select_related evaluation happens deep inside the SQL compiler,
    the only viable way to make object pool for select_related is to monkeypatch RelatedPopulator.
    """
    original_populate = RelatedPopulator.populate
    original_init = RelatedPopulator.__init__

    def __enter__(self):
        self.apply()

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.revert()

    @staticmethod
    def apply():
        RelatedPopulator.__init__ = init_with_cache
        RelatedPopulator.populate = caching_populate

    @staticmethod
    def revert():
        RelatedPopulator.__init__ = original_init
        RelatedPopulator.populate = original_populate
