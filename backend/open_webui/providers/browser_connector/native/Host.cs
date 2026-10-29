// SPDX-License-Identifier: Apache-2.0
// Windows Native Messaging transport. No secrets/configuration are persisted.
using System;
using System.IO;
using System.Net;
using System.Text;
using System.Text.RegularExpressions;
using System.Collections.Generic;
using System.Security.Cryptography;
using System.Web.Script.Serialization;

class Host {
 const string Origin="chrome-extension://jaljomgoclehkemckjhifflhmlllfopc/";
 static JavaScriptSerializer Json=new JavaScriptSerializer { MaxJsonLength=131072, RecursionLimit=8 };
 static object Result(bool ok,string code) { return new Dictionary<string,object>{{"ok",ok},{"code",code}}; }
 static string Nonce() { byte[] value=new byte[32];using(var rng=RandomNumberGenerator.Create())rng.GetBytes(value);return Convert.ToBase64String(value); }
 static string Protect(object value) { return Convert.ToBase64String(ProtectedData.Protect(Encoding.UTF8.GetBytes(Json.Serialize(value)),null,DataProtectionScope.CurrentUser)); }
 static bool Proof(Dictionary<string,object> value,string expected) {
  object found;if(!value.TryGetValue("proof",out found)||!(found is string))return false;
  byte[] a=Encoding.UTF8.GetBytes((string)found),b=Encoding.UTF8.GetBytes(expected);int difference=a.Length^b.Length;
  for(int i=0;i<b.Length;i++)difference|=(i<a.Length?a[i]:0)^b[i];return difference==0;
 }
 static void Reply(object value) {
  byte[] body=Encoding.UTF8.GetBytes(Json.Serialize(value));
  Stream output=Console.OpenStandardOutput();byte[] length=BitConverter.GetBytes(body.Length);
  output.Write(length,0,4);output.Write(body,0,body.Length);output.Flush();
 }
 static byte[] Read(Stream input,int count) {
  byte[] bytes=new byte[count];int offset=0;
  while(offset<count) { int read=input.Read(bytes,offset,count-offset);if(read==0)throw new IOException();offset+=read; }
  return bytes;
 }
 static bool Text(Dictionary<string,object> value,string key,int min,int max) {
  object found;if(!value.TryGetValue(key,out found)||!(found is string))return false;
  string text=(string)found;
  return text.Length>=min&&text.Length<=max&&!text.Contains("\r")&&!text.Contains("\n");
 }
 static Dictionary<string,object> Post(string endpoint,object body) {
  int port=8080;
#if BRIDGE_TEST
  string fixture=Environment.GetEnvironmentVariable("OWUI_BRIDGE_TEST_PORT");
  if(fixture!=null)port=Int32.Parse(fixture);
#endif
  HttpWebRequest request=(HttpWebRequest)WebRequest.Create("http://127.0.0.1:"+port+"/api/v1/local-providers/dsw2api/browser/"+endpoint);
  request.Method="POST";request.Proxy=null;request.AllowAutoRedirect=false;request.Timeout=120000;request.ReadWriteTimeout=120000;
  request.ContentType="application/json; charset=utf-8";
  request.Headers["Origin"]=Origin.TrimEnd('/');request.Headers["X-OWUI-Connector"]="jaljomgoclehkemckjhifflhmlllfopc";
  byte[] data=Encoding.UTF8.GetBytes(Json.Serialize(body));request.ContentLength=data.Length;
  using(Stream output=request.GetRequestStream())output.Write(data,0,data.Length);
  using(HttpWebResponse response=(HttpWebResponse)request.GetResponse()) {
   if(response.StatusCode!=HttpStatusCode.OK)throw new IOException();
   using(Stream stream=response.GetResponseStream())using(MemoryStream buffer=new MemoryStream()) {
    byte[] block=new byte[4096];int size;
    while((size=stream.Read(block,0,block.Length))>0) { if(buffer.Length+size>65536)throw new IOException();buffer.Write(block,0,size); }
    return Json.Deserialize<Dictionary<string,object>>(Encoding.UTF8.GetString(buffer.ToArray()));
   }
  }
 }
 static object Handle(Dictionary<string,object> value) {
  if(value==null||!Text(value,"state",64,64)||!Regex.IsMatch((string)value["state"],"\\A[a-f0-9]{64}\\z"))return Result(false,"INVALID_STATE");
  if(!value.ContainsKey("port")||!(value["port"] is int)||(int)value["port"]!=8080)return Result(false,"INVALID_PORT");
  string action=value.ContainsKey("action")?value["action"] as string:null;
  if(action!="check"&&action!="connect")return Result(false,"INVALID_ACTION");
  string challenge=Nonce();
  var check=Post("check",new Dictionary<string,object>{{"state",value["state"]},{"challenge",Protect(new Dictionary<string,object>{{"purpose","owui-dsw-check-v2"},{"state",value["state"]},{"nonce",challenge}})}});
  if(!check.ContainsKey("ok")||!Object.Equals(check["ok"],true))return Result(false,check.ContainsKey("code")&&Object.Equals(check["code"],"DEEPSEEK_ACCOUNT_BLOCKED")?"DEEPSEEK_ACCOUNT_BLOCKED":"HANDOFF_REJECTED");
  if(!Proof(check,challenge))return Result(false,"UNTRUSTED_LOCAL_PEER");
  if(action=="check")return Result(true,"AUTHORIZED");
  if(!Object.Equals(value.ContainsKey("origin")?value["origin"]:null,"https://chat.deepseek.com")||!Text(value,"token",20,16384)||!Text(value,"cookies",1,65536))return Result(false,"INVALID_SESSION");
  string acknowledgment=Nonce();
  string envelope=Protect(new Dictionary<string,object>{{"purpose","owui-dsw-session-v2"},{"state",value["state"]},{"origin",value["origin"]},{"token",value["token"]},{"cookies",value["cookies"]},{"nonce",acknowledgment}});
  var result=Post("callback",new Dictionary<string,object>{{"state",value["state"]},{"protected_session",envelope}});
  return Result(result.ContainsKey("connected")&&Object.Equals(result["connected"],true)&&Proof(result,acknowledgment),"ACCOUNT_HANDOFF");
 }
 static int Main(string[] args) {
  try {
   if(args.Length<1||args[0]!=Origin) { Reply(Result(false,"INVALID_EXTENSION"));return 2; }
   Stream input=Console.OpenStandardInput();uint length=BitConverter.ToUInt32(Read(input,4),0);
   if(length==0||length>131072) { Reply(Result(false,"INVALID_SIZE"));return 2; }
   object value=Handle(Json.Deserialize<Dictionary<string,object>>(Encoding.UTF8.GetString(Read(input,(int)length))));
   Reply(value);return 0;
  }catch { Reply(Result(false,"BRIDGE_UNAVAILABLE"));return 1; }
 }
}
