import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))


class PhoneLocationTests(unittest.TestCase):
    def test_atomic_replace_failure_preserves_existing_bookmarks(self):
        from photo_organizer.phone_locations import PhoneLocationStore
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'phone_locations.json'
            store = PhoneLocationStore(path)
            store.save([{'label': 'photos', 'device': 'Galaxy', 'components': ['Storage']}])
            before = path.read_bytes()
            with patch('photo_organizer.phone_locations.os.replace', side_effect=OSError('blocked')):
                with self.assertRaises(OSError):
                    store.save([])
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_roundtrip_and_corrupt_or_oversized_input(self):
        from photo_organizer.phone_locations import PhoneLocationStore
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'phone_locations.json';store=PhoneLocationStore(path)
            data=[{'label':'사진 보관','device':'Galaxy','components':['Internal storage','Pictures','휴대폰']}]
            self.assertEqual(store.load(),[])
            store.save(data)
            self.assertEqual(store.load(),data)
            self.assertNotIn('id',path.read_text(encoding='utf-8'))
            path.write_text('{broken')
            self.assertEqual(store.load(),[])
            path.write_text(' '*65537)
            self.assertEqual(store.load(),[])

    def test_invalid_bookmarks_rejected_and_previous_bytes_preserved(self):
        from photo_organizer.phone_locations import PhoneLocationStore
        good={'label':'사진','device':'phone','components':['Storage','Pictures']}
        invalid=[dict(good,id='session-id'),dict(good,components=['bad/name']),dict(good,components=['bad\\name']),
                 dict(good,components=['']),dict(good,label=''),dict(good,components=['x']*65),
                 dict(good,device=True),dict(good,label='x'*256)]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'phone_locations.json';store=PhoneLocationStore(path)
            store.save([good]);before=path.read_bytes()
            for bookmark in invalid:
                with self.subTest(bookmark=bookmark),self.assertRaises(ValueError):store.save([bookmark])
                self.assertEqual(path.read_bytes(),before)
            with self.assertRaises(ValueError):store.save([good]*101)
            self.assertEqual(list(path.parent.iterdir()),[path])

    def test_resolve_reenumerates_names_and_rejects_ambiguous_missing_without_writes(self):
        from photo_organizer.phone_locations import resolve_location
        entry=lambda id,name:SimpleNamespace(id=id,name=name,is_folder=True)
        class Backend:
            def __init__(self):self.calls=[]
            def list_children(self,parent):
                self.calls.append(parent)
                return {'DEVICE':[entry('fresh-storage','Internal storage')],
                        'fresh-storage':[entry('fresh-pictures','Pictures')],
                        'fresh-pictures':[entry('leaf','Photos')]}[parent]
        backend=Backend()
        stack,children=resolve_location(backend,['internal STORAGE','pictures'])
        self.assertEqual(stack,[('fresh-storage','Internal storage'),('fresh-pictures','Pictures')])
        self.assertEqual(children[0].id,'leaf')
        self.assertEqual(backend.calls,['DEVICE','fresh-storage','fresh-pictures'])
        with self.assertRaises(ValueError):resolve_location(Backend(),['missing'])
        backend=SimpleNamespace(list_children=lambda parent:[entry('a','Storage'),entry('b','STORAGE')])
        with self.assertRaises(ValueError):resolve_location(backend,['Storage'])

    def test_none_store_and_empty_components(self):
        from photo_organizer.phone_locations import PhoneLocationStore,resolve_location
        self.assertEqual(PhoneLocationStore(None).load(),[])
        PhoneLocationStore(None).save([])
        entries=[SimpleNamespace(id='s',name='Storage',is_folder=True)]
        self.assertEqual(resolve_location(SimpleNamespace(list_children=lambda parent:entries),[]),([],entries))
