// Reads only the one-time login handoff, never page passwords or Google data.
(() => {
  const params=new URLSearchParams(location.hash.slice(1));
  const value=params.get('owui-dsw2api');
  if(!value || !/^[a-f0-9]{64}\.\d{1,5}$/.test(value))return;
  const [state,port]=value.split('.');
  if(Number(port)<1 || Number(port)>65535)return;
  chrome.runtime.sendMessage({type:'owui-login',state,port:Number(port)});
})();
