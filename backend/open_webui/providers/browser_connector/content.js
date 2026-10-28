// Pass only the handoff nonce; no credentials are read here.
(() => {
 const value=new URLSearchParams(location.hash.slice(1)).get('owui-dsw2api');
 if(!value||!/^[a-f0-9]{64}\.8080$/.test(value))return;
 chrome.runtime.sendMessage({action:'owui-flow',state:value.split('.')[0],port:8080});
})();
