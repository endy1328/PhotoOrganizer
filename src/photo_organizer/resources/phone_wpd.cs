// Native COM ABI from Windows SDK PortableDeviceApi.h/PortableDeviceTypes.h.
// Replacement uses verified staging and exact-object, nonrecursive cleanup.
using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Web.Script.Serialization;

namespace PhotoOrganizerWpd {
 [StructLayout(LayoutKind.Sequential, Pack=4)]
 struct Key { public Guid format; public uint id; public Key(string f,uint i) {format=new Guid(f);id=i;} }
 public interface IRemoteObjects {
  Dictionary<string,object> Stat(string id,string parent);
  List<Dictionary<string,object>> Children(string parent);
  void Rename(string id,string parent,string name);
  void DeleteBackup(string id,string parent,string name,object size);
 }
 public static class Replacement {
  static string Text(Dictionary<string,object> e,string key){return (string)e[key];}
  static bool SameSize(object a,object b){return a!=null&&b!=null&&Convert.ToUInt64(a)==Convert.ToUInt64(b);}
  static void Verify(Dictionary<string,object> actual,Dictionary<string,object> expected,string name){
   if(Text(actual,"id")!=Text(expected,"id")||Text(actual,"name")!=name||(bool)actual["is_folder"]||!SameSize(actual["size"],expected["size"]))throw new IOException("Replacement object verification failed.");
  }
  public static Dictionary<string,object> Complete(IRemoteObjects remote,string parent,string finalName,Dictionary<string,object> old,Dictionary<string,object> stage,string stageName,string backupName,Action notify){
   string oldId=Text(old,"id"),newId=Text(stage,"id"),oldName=Text(old,"name");bool exchanging=false,deleting=false;
   try {
    if(oldId==newId||!String.Equals(oldName,finalName,StringComparison.OrdinalIgnoreCase))throw new IOException("Original object identity changed.");
    Verify(remote.Stat(oldId,parent),old,oldName);Verify(remote.Stat(newId,parent),stage,stageName);
    int matches=0;foreach(var item in remote.Children(parent)) {
     string n=Text(item,"name");if(String.Equals(n,finalName,StringComparison.OrdinalIgnoreCase)){matches++;if(Text(item,"id")!=oldId)throw new IOException("Ambiguous destination objects.");}
     if(String.Equals(n,backupName,StringComparison.OrdinalIgnoreCase))throw new IOException("Backup name already exists.");
    }
    if(matches!=1)throw new IOException("Original object cannot be uniquely identified.");
    exchanging=true;remote.Rename(oldId,parent,backupName);if(notify!=null)notify();
    remote.Rename(newId,parent,finalName);if(notify!=null)notify();
    var result=remote.Stat(newId,parent);Verify(result,stage,finalName);
    Verify(remote.Stat(oldId,parent),old,backupName);if(notify!=null)notify();
    deleting=true;remote.DeleteBackup(oldId,parent,backupName,old["size"]);return result;
   }catch(Exception error){
    string recovery="";
    if(exchanging&&!deleting){
     try {var current=remote.Stat(newId,parent);if(Text(current,"name")==finalName)remote.Rename(newId,parent,stageName);}catch(Exception e){recovery+=" New object recovery: "+e.Message;}
     try {var current=remote.Stat(oldId,parent);if(Text(current,"name")==backupName)remote.Rename(oldId,parent,oldName);}catch(Exception e){recovery+=" Original recovery: "+e.Message;}
    }
    throw new IOException("Replacement not confirmed. Inspect recovery objects: "+stageName+", "+backupName+". "+error.Message+recovery,error);
   }
  }
 }
 public class Server : IRemoteObjects {
  const string ObjectProperties="EF6B490D-5CD8-437A-AFFC-DA8B60EE4A3C";
  static Guid Folder=new Guid("27E2E392-A111-48E0-AB0C-E17705A05F85");
  static Guid Functional=new Guid("99ED0160-17FF-4C44-9D98-1D7A6F941921");
  static Guid Storage=new Guid("23F05BBC-15DE-4C2A-A55B-A9AF5CE412EF");
  static JavaScriptSerializer json=new JavaScriptSerializer();
  IntPtr device,content,properties;
  [DllImport("ole32.dll")] static extern int CoInitializeEx(IntPtr reserved,uint flags);
  [DllImport("ole32.dll")] static extern void CoUninitialize();
  [DllImport("ole32.dll")] static extern int PropVariantClear(IntPtr value);
  [DllImport("ole32.dll")] static extern int CoCreateInstance(ref Guid cls,IntPtr outer,uint ctx,ref Guid iid,out IntPtr obj);
  [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate uint Release(IntPtr self);
  [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int Query(IntPtr self,ref Guid iid,out IntPtr obj);
  [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int Simple(IntPtr self);
  [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int GetInterface(IntPtr self,out IntPtr value);
  [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int Devices(IntPtr self,IntPtr ids,ref uint count);
  [UnmanagedFunctionPointer(CallingConvention.StdCall,CharSet=CharSet.Unicode)] delegate int Friendly(IntPtr self,[MarshalAs(UnmanagedType.LPWStr)] string id,IntPtr buffer,ref uint count);
  [UnmanagedFunctionPointer(CallingConvention.StdCall,CharSet=CharSet.Unicode)] delegate int Open(IntPtr self,[MarshalAs(UnmanagedType.LPWStr)] string id,IntPtr values);
  [UnmanagedFunctionPointer(CallingConvention.StdCall,CharSet=CharSet.Unicode)] delegate int EnumObjects(IntPtr self,uint flags,[MarshalAs(UnmanagedType.LPWStr)] string parent,IntPtr filter,out IntPtr enumerator);
  [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int Next(IntPtr self,uint count,IntPtr ids,ref uint fetched);
  [UnmanagedFunctionPointer(CallingConvention.StdCall,CharSet=CharSet.Unicode)] delegate int GetValues(IntPtr self,[MarshalAs(UnmanagedType.LPWStr)] string id,IntPtr keys,out IntPtr values);
  [UnmanagedFunctionPointer(CallingConvention.StdCall,CharSet=CharSet.Unicode)] delegate int SetString(IntPtr self,ref Key key,[MarshalAs(UnmanagedType.LPWStr)] string value);
  [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int GetString(IntPtr self,ref Key key,out IntPtr value);
  [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int SetLarge(IntPtr self,ref Key key,ulong value);
  [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int GetLarge(IntPtr self,ref Key key,out ulong value);
  [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int SetGuid(IntPtr self,ref Key key,ref Guid value);
  [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int GetGuid(IntPtr self,ref Key key,out Guid value);
  [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int CreateFolder(IntPtr self,IntPtr values,out IntPtr id);
  [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int CreateData(IntPtr self,IntPtr values,out IntPtr stream,ref uint bufferSize,IntPtr cookie);
  [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int Write(IntPtr self,IntPtr buffer,uint count,out uint written);
  [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int Commit(IntPtr self,uint flags);
  [UnmanagedFunctionPointer(CallingConvention.StdCall,CharSet=CharSet.Unicode)] delegate int Attributes(IntPtr self,[MarshalAs(UnmanagedType.LPWStr)] string id,ref Key key,out IntPtr values);
  [UnmanagedFunctionPointer(CallingConvention.StdCall,CharSet=CharSet.Unicode)] delegate int SetValues(IntPtr self,[MarshalAs(UnmanagedType.LPWStr)] string id,IntPtr values,out IntPtr results);
  [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int GetBool(IntPtr self,ref Key key,out int value);
  [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int GetError(IntPtr self,ref Key key,out int value);
  [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int CollectionCount(IntPtr self,out uint count);
  [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int CollectionAt(IntPtr self,uint index,IntPtr value);
  [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int CollectionAdd(IntPtr self,IntPtr value);
  [UnmanagedFunctionPointer(CallingConvention.StdCall)] delegate int DeleteObjects(IntPtr self,uint flags,IntPtr ids,out IntPtr results);
  static T Method<T>(IntPtr obj,int slot) where T:class {
   if(obj==IntPtr.Zero) throw new IOException("WPD session is not open.");
   return (T)(object)Marshal.GetDelegateForFunctionPointer(Marshal.ReadIntPtr(Marshal.ReadIntPtr(obj),slot*IntPtr.Size),typeof(T));
  }
  static void Check(int hr) {if(hr<0) Marshal.ThrowExceptionForHR(hr);}
  static void Free(ref IntPtr value) {if(value!=IntPtr.Zero) {Method<Release>(value,2)(value);value=IntPtr.Zero;}}
  static IntPtr Create(string cls,string iid) {Guid c=new Guid(cls),i=new Guid(iid);IntPtr result;Check(CoCreateInstance(ref c,IntPtr.Zero,1,ref i,out result));return result;}
  static IntPtr Values() {return Create("0c15d503-d017-47ce-9016-7b3f978721cc","6848f6f2-3155-4f86-b6f5-263eeeab3143");}
  static Key K(uint id) {return new Key(ObjectProperties,id);}
  static void PutString(IntPtr values,Key key,string text) {Check(Method<SetString>(values,7)(values,ref key,text));}
  static void PutGuid(IntPtr values,Key key,Guid value) {Check(Method<SetGuid>(values,27)(values,ref key,ref value));}
  static string StringValue(IntPtr values,Key key) {IntPtr ptr;int hr=Method<GetString>(values,8)(values,ref key,out ptr);if(hr<0)return null;return TakeString(ptr);}
  static Guid GuidValue(IntPtr values,Key key) {Guid value;return Method<GetGuid>(values,28)(values,ref key,out value)<0?Guid.Empty:value;}
  static string TakeString(IntPtr ptr) {try{return Marshal.PtrToStringUni(ptr);}finally{Marshal.FreeCoTaskMem(ptr);}}
  static Dictionary<string,object> Entry(string id,string name,bool folder,object size) {return new Dictionary<string,object>{{"id",id},{"name",name},{"is_folder",folder},{"size",size}};}
  static void Emit(object data) {Console.Out.WriteLine(json.Serialize(data));Console.Out.Flush();}
  static bool Progress(long bytes,string phase) {return Progress(bytes,phase,true);}
  static bool Progress(long bytes,string phase,bool cancellable) {
   Emit(new Dictionary<string,object>{{"event","progress"},{"bytes",bytes},{"phase",phase},{"cancellable",cancellable}});
   string line=Console.In.ReadLine();if(line==null)return false;
   var ack=json.Deserialize<Dictionary<string,object>>(line);return ack.ContainsKey("continue")&&Convert.ToBoolean(ack["continue"]);
  }
  static void Name(string value) {if(String.IsNullOrEmpty(value)||value=="."||value==".."||value.IndexOfAny(new char[]{'/','\\','\0'})>=0)throw new ArgumentException("A single object name is required.");}
  void Close() {Free(ref properties);Free(ref content);if(device!=IntPtr.Zero){try{Method<Simple>(device,8)(device);}finally{Free(ref device);}}}
  object ListDevices() {
   IntPtr manager=Create("0af10cec-2ecd-4b92-9581-34f6ae0637f3","a1567595-4c2f-4574-a6fa-ecef917b9a40");
   IntPtr ids=IntPtr.Zero;uint count=0,capacity=0;var entries=new List<object>();
   try {
    Check(Method<Simple>(manager,4)(manager));Check(Method<Devices>(manager,3)(manager,IntPtr.Zero,ref count));if(count==0)return entries;
    capacity=count;ids=Marshal.AllocCoTaskMem(checked((int)capacity*IntPtr.Size));for(int n=0;n<capacity;n++)Marshal.WriteIntPtr(ids,n*IntPtr.Size,IntPtr.Zero);
    Check(Method<Devices>(manager,3)(manager,ids,ref count));if(count>capacity)throw new IOException("Device list changed. Refresh devices.");
    for(int n=0;n<count;n++) {
     string id=TakeString(Marshal.ReadIntPtr(ids,n*IntPtr.Size));Marshal.WriteIntPtr(ids,n*IntPtr.Size,IntPtr.Zero);uint length=0;string name=id;
     if(Method<Friendly>(manager,5)(manager,id,IntPtr.Zero,ref length)>=0&&length>0) {
      IntPtr buffer=Marshal.AllocCoTaskMem(checked((int)length*2));try{Check(Method<Friendly>(manager,5)(manager,id,buffer,ref length));name=Marshal.PtrToStringUni(buffer);}finally{Marshal.FreeCoTaskMem(buffer);}
     }
     entries.Add(Entry(id,name,true,null));
    }
    return entries;
   }finally{if(ids!=IntPtr.Zero){for(int n=0;n<capacity;n++){IntPtr p=Marshal.ReadIntPtr(ids,n*IntPtr.Size);if(p!=IntPtr.Zero)Marshal.FreeCoTaskMem(p);}Marshal.FreeCoTaskMem(ids);}Free(ref manager);}
  }
  void OpenDevice(string id) {
   Close();IntPtr values=Values();
   try {PutString(values,new Key("204D9F0C-2292-4080-9F42-40664E70F859",2),"PhotoOrganizer");device=Create("728a21c5-3d9e-48d7-9810-864848f0f404","625e2df8-6392-4cf0-9ad1-3cfa5f17775c");Check(Method<Open>(device,3)(device,id,values));Check(Method<GetInterface>(device,5)(device,out content));Check(Method<GetInterface>(content,4)(content,out properties));}
   catch{Close();throw;}finally{Free(ref values);}
  }
  public Dictionary<string,object> Stat(string id,string expectedParent) {
   IntPtr values;Check(Method<GetValues>(properties,5)(properties,id,IntPtr.Zero,out values));
   try {
    string name=StringValue(values,K(12))??StringValue(values,K(4));if(name==null)throw new IOException("Device object name cannot be read.");
    if(expectedParent!=null&&StringValue(values,K(3))!=expectedParent)throw new IOException("Device parent verification failed.");
    Guid type=GuidValue(values,K(7));bool folder=type==Folder||(type==Functional&&GuidValue(values,new Key("8F052D93-ABCA-4FC5-A5AC-B01DF4DBE598",2))==Storage);
    ulong size;Key key=K(11);object length=Method<GetLarge>(values,14)(values,ref key,out size)<0?null:(object)size;return Entry(id,name,folder,length);
   }finally{Free(ref values);}
  }
  public List<Dictionary<string,object>> Children(string parent) {
   IntPtr enumerator;Check(Method<EnumObjects>(content,3)(content,0,parent,IntPtr.Zero,out enumerator));var entries=new List<Dictionary<string,object>>();IntPtr one=Marshal.AllocCoTaskMem(IntPtr.Size);Marshal.WriteIntPtr(one,IntPtr.Zero);
   try {while(true){uint fetched=0;Marshal.WriteIntPtr(one,IntPtr.Zero);int hr=Method<Next>(enumerator,3)(enumerator,1,one,ref fetched);Check(hr);if(fetched==0)break;string id=TakeString(Marshal.ReadIntPtr(one));Marshal.WriteIntPtr(one,IntPtr.Zero);entries.Add(Stat(id,parent));}return entries;}
   finally{IntPtr left=Marshal.ReadIntPtr(one);if(left!=IntPtr.Zero)Marshal.FreeCoTaskMem(left);Marshal.FreeCoTaskMem(one);Free(ref enumerator);}
  }
  void EnsureNew(string parent,string name) {Name(name);foreach(var child in Children(parent))if(String.Equals((string)child["name"],name,StringComparison.OrdinalIgnoreCase))throw new ExistingNameException(name);}
  void RenameAllowed(string id) {
   IntPtr attributes=IntPtr.Zero;Key key=K(12);try {
    Check(Method<Attributes>(properties,4)(properties,id,ref key,out attributes));
    Key writable=new Key("AB7943D8-6332-445F-A00D-8D5EF1E96F37",4);int permitted;
    Check(Method<GetBool>(attributes,24)(attributes,ref writable,out permitted));if(permitted==0)throw new IOException("Device does not support safe filename replacement.");
   }finally{Free(ref attributes);}
  }
  public void Rename(string id,string parent,string name) {
   Name(name);EnsureNew(parent,name);Stat(id,parent);RenameAllowed(id);
   IntPtr values=Values(),results=IntPtr.Zero;Key key=K(12);
   try {
    PutString(values,key,name);int hr=Method<SetValues>(properties,6)(properties,id,values,out results);Check(hr);
    if(results==IntPtr.Zero)throw new IOException("Rename property result was not provided.");
    int propertyResult;Check(Method<GetError>(results,20)(results,ref key,out propertyResult));Check(propertyResult);
    if((string)Stat(id,parent)["name"]!=name)throw new IOException("Renamed object verification failed.");
   }finally{Free(ref results);Free(ref values);}
  }
  public void DeleteBackup(string id,string parent,string name,object size) {
   var entry=Stat(id,parent);
   if((bool)entry["is_folder"]||(string)entry["name"]!=name||size==null||entry["size"]==null||Convert.ToUInt64(entry["size"])!=Convert.ToUInt64(size))throw new IOException("Backup identity changed; deletion refused.");
   IntPtr ids=IntPtr.Zero,results=IntPtr.Zero,variant=Marshal.AllocCoTaskMem(IntPtr.Size==8?24:16);
   for(int n=0;n<(IntPtr.Size==8?24:16);n++)Marshal.WriteByte(variant,n,0);
   try {
    ids=Create("08a99e2f-6d6d-4b80-af5a-baf2bcbe4cb9","89b2e422-4f1b-4316-bcef-a44afea83eb3");
    Marshal.WriteInt16(variant,31);Marshal.WriteIntPtr(variant,8,Marshal.StringToCoTaskMemUni(id));
    Check(Method<CollectionAdd>(ids,5)(ids,variant));Check(PropVariantClear(variant));
    int hr=Method<DeleteObjects>(content,8)(content,0,ids,out results);Check(hr);
    if(results==IntPtr.Zero)throw new IOException("Backup deletion result was not provided.");
    uint count;Check(Method<CollectionCount>(results,3)(results,out count));if(count!=1)throw new IOException("Unexpected backup deletion result count.");
    Check(Method<CollectionAt>(results,4)(results,0,variant));
    if(Marshal.ReadInt16(variant)!=10)throw new IOException("Backup deletion returned an invalid result.");Check(Marshal.ReadInt32(variant,8));
    foreach(var child in Children(parent))if((string)child["id"]==id)throw new IOException("Backup deletion could not be verified.");
   }finally{PropVariantClear(variant);Marshal.FreeCoTaskMem(variant);Free(ref results);Free(ref ids);}
  }
  object Overwrite(string parent,string name,string source,string existingId,string stageName,string backupName) {
   Name(name);var old=Stat(existingId,parent);int matches=0;
   foreach(var child in Children(parent))if(String.Equals((string)child["name"],name,StringComparison.OrdinalIgnoreCase)){matches++;if((string)child["id"]!=existingId)throw new ExistingNameException(name);}
   if(matches!=1||(bool)old["is_folder"]||!String.Equals((string)old["name"],name,StringComparison.OrdinalIgnoreCase))throw new ExistingNameException(name);
   if(old["size"]==null)throw new IOException("Original size cannot be verified; replacement refused.");
   RenameAllowed(existingId);
   IntPtr info=IntPtr.Zero;try {Check(Method<GetValues>(properties,5)(properties,existingId,IntPtr.Zero,out info));Key key=K(26);int allowed;Check(Method<GetBool>(info,24)(info,ref key,out allowed));if(allowed==0)throw new IOException("Device disallows backup cleanup; replacement refused.");}finally{Free(ref info);}
   Name(stageName);Name(backupName);
   if(!stageName.StartsWith(".photoorganizer_stage_",StringComparison.Ordinal)||!backupName.StartsWith(".photoorganizer_backup_",StringComparison.Ordinal)||String.Equals(stageName,name,StringComparison.OrdinalIgnoreCase)||String.Equals(backupName,name,StringComparison.OrdinalIgnoreCase)||String.Equals(stageName,backupName,StringComparison.OrdinalIgnoreCase))throw new ArgumentException("Invalid recovery object names.");
   Dictionary<string,object> stage;
   try {stage=(Dictionary<string,object>)Upload(parent,stageName,source);RenameAllowed((string)stage["id"]);}
   catch(Exception e){if(e is OperationCanceledException)throw;throw new IOException("Staged replacement could not be confirmed. Original remains untouched; inspect "+stageName+". "+e.Message,e);}
   if(!Progress(Convert.ToInt64(stage["size"]),"swap_prepare"))throw new OperationCanceledException("Cancelled before replacement. Original remains untouched; staged file retained: "+stageName);
   return Replacement.Complete(this,parent,name,old,stage,stageName,backupName,delegate {if(!Progress(Convert.ToInt64(stage["size"]),"swap",false))throw new IOException("Replacement acknowledgement connection ended.");});
  }
  IntPtr ObjectValues(string parent,string name,bool folder,long size) {
   IntPtr values=Values();
   try {
    PutString(values,K(3),parent);PutString(values,K(4),name);PutString(values,K(12),name);
    Guid type=folder?Folder:new Guid("0085E0A6-8D34-45D7-BC5C-447E59C73D48");Guid format=new Guid(folder?"30010000-AE6C-4804-98BA-C57B46965FE7":"30000000-AE6C-4804-98BA-C57B46965FE7");
    if(!folder){string ext=Path.GetExtension(name).ToLowerInvariant();if(ext==".jpg"||ext==".jpeg"||ext==".png"){type=new Guid("EF2107D5-A52A-4243-A26B-62D4176D7603");format=new Guid(ext==".png"?"380B0000-AE6C-4804-98BA-C57B46965FE7":"38010000-AE6C-4804-98BA-C57B46965FE7");}if(ext==".mp4"){type=new Guid("9261B03C-3D78-4519-85E3-02C5E1F50BB9");format=new Guid("B9820000-AE6C-4804-98BA-C57B46965FE7");}Key key=K(11);Check(Method<SetLarge>(values,13)(values,ref key,(ulong)size));}
    PutGuid(values,K(7),type);PutGuid(values,K(6),format);return values;
   }catch{Free(ref values);throw;}
  }
  object MakeFolder(string parent,string name) {
   EnsureNew(parent,name);IntPtr values=ObjectValues(parent,name,true,0),id=IntPtr.Zero;
   try{Check(Method<CreateFolder>(content,6)(content,values,out id));string objectId=TakeString(id);id=IntPtr.Zero;var result=Stat(objectId,parent);if((string)result["name"]!=name||!(bool)result["is_folder"])throw new IOException("Created folder verification failed.");return result;}
   finally{if(id!=IntPtr.Zero)Marshal.FreeCoTaskMem(id);Free(ref values);}
  }
  object Upload(string parent,string name,string source) {
   EnsureNew(parent,name);if(!Progress(0,"prepare"))throw new OperationCanceledException("Cancelled before creation.");
   IntPtr values=IntPtr.Zero,stream=IntPtr.Zero;bool committed=false;
   try {
    using(var file=new FileStream(source,FileMode.Open,FileAccess.Read,FileShare.Read)) {
     long expected=file.Length,total=0;values=ObjectValues(parent,name,false,expected);uint optimal=0;IntPtr basicStream;
     Check(Method<CreateData>(content,7)(content,values,out basicStream,ref optimal,IntPtr.Zero));
     try{Guid iid=new Guid("88e04db3-1012-4d64-9996-f703a950d3f4");Check(Method<Query>(basicStream,0)(basicStream,ref iid,out stream));}finally{Free(ref basicStream);}
     int blockSize=(int)Math.Max(4096,Math.Min(optimal==0?65536U:optimal,1048576U));byte[] buffer=new byte[blockSize];int read;
     while((read=file.Read(buffer,0,buffer.Length))>0) {
      GCHandle pinned=GCHandle.Alloc(buffer,GCHandleType.Pinned);
      try{int offset=0;while(offset<read){uint written;Check(Method<Write>(stream,4)(stream,IntPtr.Add(pinned.AddrOfPinnedObject(),offset),(uint)(read-offset),out written));if(written==0||written>read-offset)throw new IOException("Invalid WPD write count.");offset+=(int)written;total+=written;}}finally{pinned.Free();}
      if(!Progress(total,"write"))throw new OperationCanceledException("Transfer cancelled.");
     }
     if(total!=expected||file.Length!=expected)throw new IOException("Source size changed during transfer.");
     EnsureNew(parent,name);if(!Progress(total,"commit"))throw new OperationCanceledException("Cancelled before Commit.");
     Check(Method<Commit>(stream,8)(stream,0));committed=true;IntPtr id;Check(Method<GetInterface>(stream,14)(stream,out id));string objectId=TakeString(id);var result=Stat(objectId,parent);
     if((string)result["name"]!=name||(bool)result["is_folder"]||result["size"]==null||Convert.ToUInt64(result["size"])!=(ulong)expected)throw new IOException("Committed object verification failed. Inspect the newly created object.");return result;
    }
   }finally{
    try {
     if(stream!=IntPtr.Zero&&!committed) {
      int reverted=Method<Simple>(stream,9)(stream);
      if(reverted<0)throw new IOException("Transfer rollback could not be confirmed. Inspect the phone after reconnecting.");
     }
    }finally{Free(ref stream);Free(ref values);}
   }
  }
  public static void Run() {
   Console.InputEncoding=new UTF8Encoding(false);Console.OutputEncoding=new UTF8Encoding(false);int initialized=CoInitializeEx(IntPtr.Zero,2);Check(initialized);var server=new Server();
   try {
    Emit(new Dictionary<string,object>{{"event","ready"}});string line;
    while((line=Console.In.ReadLine())!=null) {
     bool closing=false;
     try {
      var req=json.Deserialize<Dictionary<string,object>>(line);string op=(string)req["op"];object result=null;
      if(op=="devices")result=server.ListDevices();else if(op=="open")server.OpenDevice((string)req["id"]);else if(op=="children")result=server.Children((string)req["parent"]);else if(op=="folder")result=server.MakeFolder((string)req["parent"],(string)req["name"]);else if(op=="upload")result=server.Upload((string)req["parent"],(string)req["name"],(string)req["source"]);else if(op=="overwrite")result=server.Overwrite((string)req["parent"],(string)req["name"],(string)req["source"],(string)req["existing_id"],(string)req["stage_name"],(string)req["backup_name"]);else if(op=="close"){server.Close();closing=true;}else throw new ArgumentException("Unsupported operation.");
      Emit(new Dictionary<string,object>{{"ok",true},{"result",result}});
     }catch(Exception error){Emit(new Dictionary<string,object>{{"ok",false},{"kind",error is ExistingNameException?"exists":error is OperationCanceledException?"cancelled":"io"},{"error",error.Message}});}
     if(closing)break;
    }
   }finally{server.Close();CoUninitialize();}
  }
  class ExistingNameException:IOException{public ExistingNameException(string name):base("Remote object already exists: "+name){}}
 }
}
