// SPDX-License-Identifier: Apache-2.0
async function connect(action){
 const buttons=Array.from(document.querySelectorAll('button')),status=document.getElementById('status');
 buttons.forEach(button=>button.disabled=true);status.textContent='Подключение…';
 try{const value=await chrome.runtime.sendMessage({action});status.textContent=value?.ok?'Сессия передана выбранным приложениям. Это не подтверждает доступность генерации.':value?.code==='START_IN_OWUI'?'Сначала нажмите «Войти» в настройках DSW2API в OWUI.':value?.code==='SIGN_IN_REQUIRED'?'Войдите в DeepSeek в обычной вкладке браузера.':'Подключение не завершено. Проверьте запуск приложения и локального моста.';}
 catch{status.textContent='Локальный мост недоступен.';}finally{buttons.forEach(button=>button.disabled=false);}
}
document.getElementById('both').onclick=()=>connect('connect-both');
document.getElementById('connect').onclick=()=>connect('connect');
document.getElementById('owui').onclick=()=>connect('connect-owui');
void chrome.runtime.sendMessage({action:'status'}).then(value=>{if(value?.inference_blocked){document.getElementById('status').textContent='Аккаунт ограничен DeepSeek. Переподключение не снимает ограничение.';return;}if(value?.ok||value?.owui)document.getElementById('status').textContent='Cline: '+(value.ok?'подключён':'не подключён')+'. OWUI: '+(value.owui?'подключён':'не подключён')+'.';}).catch(()=>{});
