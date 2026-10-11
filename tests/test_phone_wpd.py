import sys
import base64
import os
import subprocess
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from photo_organizer.phone_wpd import WpdBackend


class WpdBackendTests(unittest.TestCase):
    def test_overwrite_uses_exact_existing_object_and_verifies_final_result(self):
        backend = WpdBackend()
        result = {"id": "new", "name": "photo.jpg", "is_folder": False, "size": 12}
        with patch.object(Path, "stat", return_value=SimpleNamespace(st_size=12)), patch.object(backend, "_request", return_value=result) as request:
            entry = backend.overwrite_file("parent", "photo.jpg", Path("photo.jpg"), lambda _: None, lambda: False, "old-id")
        self.assertEqual(entry.id, "new")
        self.assertEqual(request.call_args.args[0], "overwrite")
        self.assertEqual(request.call_args.kwargs["existing_id"], "old-id")

    def test_overwrite_cancelled_before_start_does_not_issue_swap(self):
        backend = WpdBackend()
        with patch.object(backend, "_request") as request, self.assertRaises(InterruptedError):
            backend.overwrite_file("parent", "photo.jpg", Path("photo.jpg"), lambda _: None, lambda: True, "old-id")
        request.assert_not_called()

    def test_overwrite_wrong_final_name_or_size_is_not_reported_complete(self):
        result = {"id": "new", "name": "backup.jpg", "is_folder": False, "size": 12}
        with patch.object(Path, "stat", return_value=SimpleNamespace(st_size=12)), patch.object(WpdBackend, "_request", return_value=result), self.assertRaises(OSError):
            WpdBackend().overwrite_file("parent", "photo.jpg", Path("photo.jpg"), lambda _: None, lambda: False, "old-id")

    def test_destructive_swap_finishes_even_when_cancellation_requested(self):
        sent = []
        with patch.object(WpdBackend, "_send", side_effect=sent.append):
            WpdBackend()._progress({"bytes": 12, "cancellable": False}, lambda _: None, lambda: True)
        self.assertEqual(sent, [{"continue": True}])

    def test_overwrite_connection_failure_reports_known_recovery_names(self):
        with patch.object(Path, "stat", return_value=SimpleNamespace(st_size=12)), patch.object(WpdBackend, "_request", side_effect=OSError("timeout")), self.assertRaises(OSError) as error:
            WpdBackend().overwrite_file("parent", "photo.jpg", Path("photo.jpg"), lambda _: None, lambda: False, "old")
        self.assertIn(".photoorganizer_stage_", str(error.exception))
        self.assertIn(".photoorganizer_backup_", str(error.exception))

    def test_overwrite_collision_preserves_exception_type(self):
        with patch.object(Path, "stat", return_value=SimpleNamespace(st_size=12)), patch.object(WpdBackend, "_request", side_effect=FileExistsError("changed")), self.assertRaises(FileExistsError):
            WpdBackend().overwrite_file("parent", "photo.jpg", Path("photo.jpg"), lambda _: None, lambda: False, "old")

    def test_device_and_child_entries_keep_virtual_ids(self):
        backend = WpdBackend()
        device_id = r"\\?\usb#vid_04e8&pid_6860&ms_comp_mtp#opaque"
        with patch.object(backend, "_request", return_value=[{"id": device_id, "name": "휴대폰", "is_folder": True, "size": None}]):
            self.assertEqual(backend.list_devices()[0].id, device_id)
            self.assertTrue(backend.list_children("storage:1")[0].is_folder)

    def test_upload_checks_committed_remote_size_and_name(self):
        backend = WpdBackend()
        good = {"id": "new:1", "name": "photo.jpg", "is_folder": False, "size": 12}
        with patch.object(Path, "stat", return_value=SimpleNamespace(st_size=12)), patch.object(backend, "_request", return_value=good):
            self.assertEqual(backend.upload_new("parent", "photo.jpg", Path("photo.jpg"), lambda n: None, lambda: False).size, 12)
        for change in ({"size": 11}, {"name": "renamed.jpg"}, {"is_folder": True}):
            with self.subTest(change=change), patch.object(Path, "stat", return_value=SimpleNamespace(st_size=12)), patch.object(backend, "_request", return_value={**good, **change}):
                with self.assertRaises(OSError):
                    backend.upload_new("parent", "photo.jpg", Path("photo.jpg"), lambda n: None, lambda: False)

    def test_cancelled_upload_does_not_issue_creation(self):
        backend = WpdBackend()
        with patch.object(backend, "_request") as request, self.assertRaises(InterruptedError):
            backend.upload_new("parent", "photo.jpg", Path("photo.jpg"), lambda n: None, lambda: True)
        request.assert_not_called()

    def test_protocol_error_types(self):
        for kind, error in (("exists", FileExistsError), ("cancelled", InterruptedError), ("io", OSError)):
            with self.subTest(kind=kind), self.assertRaises(error):
                WpdBackend._result({"ok": False, "kind": kind, "error": "details"})

    def test_invalid_remote_name_rejected_before_helper(self):
        backend = WpdBackend()
        for name in ("", "../file", "a/b", "a\\b", "name\x00"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                backend.create_folder("parent", name)

    def test_backend_rejects_cross_thread_com_session_use(self):
        backend = WpdBackend()
        backend._owner = threading.get_ident() + 1
        with self.assertRaises(RuntimeError):
            backend._ensure_started()

    def test_progress_messages_check_cancel_before_continuing(self):
        backend = WpdBackend()
        sent = []
        with patch.object(backend, "_send", side_effect=sent.append):
            seen = []
            backend._progress({"event": "progress", "bytes": 12}, seen.append, lambda: False)
            backend._progress({"event": "progress", "bytes": 12}, seen.append, lambda: True)
        self.assertEqual(seen, [12, 12])
        self.assertEqual(sent, [{"continue": True}, {"continue": False}])

    def test_timeout_even_after_cancellation_keeps_completion_unknown(self):
        backend = WpdBackend()
        with patch("photo_organizer.phone_wpd.time.monotonic", side_effect=[0, 61]), patch.object(backend, "_terminate") as terminate:
            with self.assertRaises(OSError) as error:
                backend._receive(60, lambda: True)
        self.assertNotIsInstance(error.exception, InterruptedError)
        terminate.assert_called_once()

    def test_upload_protocol_uses_progress_then_final_result(self):
        backend = WpdBackend()
        responses = [{"event": "progress", "bytes": 2}, {"ok": True, "result": {"id": "new"}}]
        with patch.object(backend, "_ensure_started"), patch.object(backend, "_send") as send, patch.object(backend, "_receive", side_effect=responses):
            seen = []
            result = backend._request("upload", progress=seen.append, cancelled=lambda: False, name="한글.jpg")
        self.assertEqual(result, {"id": "new"})
        self.assertEqual(seen, [2])
        self.assertEqual(send.call_args_list[-1].args[0], {"continue": True})

    def test_read_only_helper_detects_non_windows_before_starting(self):
        with patch("photo_organizer.phone_wpd.os.name", "posix"), self.assertRaises(OSError):
            WpdBackend()._ensure_started()

    def test_device_picker_filters_filesystem_volumes_and_non_usb_devices(self):
        usb = {"id": r"\\?\USB#VID_04E8&PID_6860#opaque", "name": "phone", "is_folder": True}
        volume = {"id": r"\\?\swd#wpdbusenum#volume", "name": "local drive", "is_folder": True}
        bluetooth = {"id": r"\\?\bth#device", "name": "wireless", "is_folder": True}
        with patch.object(WpdBackend, "_request", return_value=[volume, usb, bluetooth]):
            self.assertEqual([entry.name for entry in WpdBackend().list_devices()], ["phone"])

    def test_start_and_send_failure_discard_stale_helper_for_refresh(self):
        for stage in ("_ensure_started", "_send"):
            backend = WpdBackend()
            with self.subTest(stage=stage), patch.object(backend, "_ensure_started"), patch.object(backend, "_send"), patch.object(backend, stage, side_effect=OSError("connection lost")), patch.object(backend, "_terminate") as terminate:
                with self.assertRaises(OSError):
                    backend._request("devices")
                terminate.assert_called_once()

    def test_cross_thread_request_does_not_terminate_owner_session(self):
        backend = WpdBackend()
        backend._owner = threading.get_ident() + 1
        with patch.object(backend, "_terminate") as terminate, self.assertRaises(RuntimeError):
            backend._request("devices")
        terminate.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows C# compiler required")
    def test_native_replacement_state_machine_without_device_writes(self):
        helper = Path(__file__).resolve().parents[1] / "src/photo_organizer/resources/phone_wpd.cs"
        fake_source = r'''
namespace PhotoOrganizerWpd {
 public class FakeRemote : IRemoteObjects {
  public Dictionary<string,Dictionary<string,object>> Files = new Dictionary<string,Dictionary<string,object>>();
  public int Deletes; public bool FailPublish, ChangeBackup, Disconnect, FailAfterDelete;
  public FakeRemote() { Files["old"] = E("old", "photo.jpg", 5); Files["new"] = E("new", "stage.jpg", 12); }
  public static Dictionary<string,object> E(string id,string name,long size) {return new Dictionary<string,object>{{"id",id},{"name",name},{"size",size},{"is_folder",false}};}
  public Dictionary<string,object> Stat(string id,string parent) {
   if(Disconnect)throw new IOException("disconnected");
   if(!Files.ContainsKey(id))throw new IOException("not found");
   return new Dictionary<string,object>(Files[id]);
  }
  public List<Dictionary<string,object>> Children(string parent) {var result=new List<Dictionary<string,object>>(); foreach(var row in Files.Values)result.Add(new Dictionary<string,object>(row));return result;}
  public void Rename(string id,string parent,string name) {
   if(FailPublish && id=="new" && name=="photo.jpg") {FailPublish=false;throw new IOException("rename unsupported");}
   foreach(var row in Files.Values)if((string)row["name"]==name && (string)row["id"]!=id)throw new IOException("exists");
   Files[id]["name"]=name;
   if(ChangeBackup && id=="old" && name=="backup.jpg") {ChangeBackup=false;Files[id]["size"]=999L;}
  }
  public void DeleteBackup(string id,string parent,string name,object size) {Deletes++;Files.Remove(id);if(FailAfterDelete)throw new IOException("verification disconnected");}
 }
 public static class SwapTests {
  static Dictionary<string,object> Run(FakeRemote remote) {return Replacement.Complete(remote,"parent","photo.jpg",remote.Stat("old","parent"),remote.Stat("new","parent"),"stage.jpg","backup.jpg",null);}
  static void Assert(bool test,string message) {if(!test)throw new Exception(message);}
  public static void RunAll() {
   var good=new FakeRemote(); var result=Run(good);Assert((string)result["id"]=="new"&&good.Deletes==1&&!good.Files.ContainsKey("old"),"success deletes only old backup");
   var failed=new FakeRemote();failed.FailPublish=true;try{Run(failed);throw new Exception("expected failure");}catch(IOException){ }
   Assert((string)failed.Files["old"]["name"]=="photo.jpg"&&failed.Deletes==0&&failed.Files.ContainsKey("new"),"failed publish preserves old and staged new");
   var changed=new FakeRemote();changed.ChangeBackup=true;try{Run(changed);throw new Exception("expected failure");}catch(IOException){ }
   Assert(changed.Deletes==0&&changed.Files.ContainsKey("old"),"changed backup must not be deleted");
   var deleted=new FakeRemote();deleted.FailAfterDelete=true;try{Run(deleted);throw new Exception("expected failure");}catch(IOException){ }
   Assert((string)deleted.Files["new"]["name"]=="photo.jpg","uncertain delete must preserve verified final filename");
   var casing=new FakeRemote();casing.Files["old"]["name"]="PHOTO.JPG";casing.FailPublish=true;try{Run(casing);throw new Exception("expected failure");}catch(IOException){ }
   Assert((string)casing.Files["old"]["name"]=="PHOTO.JPG","rollback retains original case");
   var ambiguous=new FakeRemote();ambiguous.Files["other"]=FakeRemote.E("other","photo.jpg",7);try{Run(ambiguous);throw new Exception("expected failure");}catch(IOException){ }
   Assert(ambiguous.Deletes==0&&(string)ambiguous.Files["old"]["name"]=="photo.jpg","ambiguous name fails before mutation");
   var disconnected=new FakeRemote();var old=disconnected.Stat("old","parent");var staged=disconnected.Stat("new","parent");disconnected.Disconnect=true;
   try{Replacement.Complete(disconnected,"parent","photo.jpg",old,staged,"stage.jpg","backup.jpg",null);throw new Exception("expected failure");}catch(IOException error){Assert(error.Message.Contains("backup.jpg"),"recovery backup name is reported");}
   Assert(disconnected.Deletes==0,"disconnect must not delete");
   Console.WriteLine("SWAP_TESTS_PASS");
  }
 }
}
'''
        command = "$ErrorActionPreference='Stop'; Add-Type -TypeDefinition ((Get-Content -Raw '" + str(helper).replace("'", "''") + "') + @'\n" + fake_source + "\n'@) -ReferencedAssemblies System.dll,System.Core.dll,System.Web.Extensions.dll; [PhotoOrganizerWpd.SwapTests]::RunAll()"
        encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
        powershell = str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe")
        result = subprocess.run([powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SWAP_TESTS_PASS", result.stdout)


if __name__ == "__main__":
    unittest.main()
