/* VdkTree v1.0.2: MAX Mini App and cross-browser pairing UI contract. */
"use strict";
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const path=require("node:path");
const source=fs.readFileSync(path.resolve(__dirname,"../auth/client.js"),"utf8");

function element(tag="div"){
  return {
    tag,children:[],open:false,textContent:"",hidden:false,_html:"",cached:new Map(),
    get innerHTML(){return this._html;},
    set innerHTML(v){this._html=v;this.children=[];this.cached=new Map();},
    append(child){this.children.push(child);},
    setAttribute(k,v){this[k]=v;},
    querySelector(selector){
      if(this.tag==="dialog"&&this.children[0])return this.children[0].querySelector(selector);
      if(!this.cached.has(selector))this.cached.set(selector,element(selector));
      return this.cached.get(selector);
    },
    showModal(){this.open=true;},close(){this.open=false;},
    insertBefore(child){this.authButton=child;}
  };
}

async function render(config={}){
  const header=element("header"),dialogs=[],requests=[],storage=new Map(),timers=[];
  const doc={
    querySelector(s){return s==="header"?header:null;},
    createElement(tag){return element(tag);},
    body:{append(node){dialogs.push(node);}}
  };
  const win={
    VDK_AUTH_API:"https://vdktree.bothost.tech",
    location:{hash:config.hash||""},
    ...(config.bridge?{WebApp:config.bridge}:{})
  };
  const context={
    window:win,document:doc,URLSearchParams,Event:undefined,
    setInterval(callback){const id={callback,active:true};timers.push(id);return id;},
    clearInterval(id){id.active=false;},
    sessionStorage:{
      getItem(k){return storage.get(k)||null;},
      setItem(k,v){storage.set(k,v);},
      removeItem(k){storage.delete(k);}
    },
    fetch:async(url,opts)=>{
      requests.push({url,opts});
      let body;
      if(url.endsWith("/device/start"))body={
        request_id:"a".repeat(32),verifier:"v".repeat(48),code:"ABCDEF23",expires_in:300
      };
      else if(url.endsWith("/device/poll"))body=config.approved?{
        status:"authenticated",token:"SESSION_TEST_ONLY",
        user:{id:"user-1",display_name:"Тест MAX",role:"user",login:null,has_password:false}
      }:{status:"pending"};
      else if(url.endsWith("/device/approve"))body={ok:true,status:"approved"};
      else body={
        token:"SESSION_TEST_ONLY",
        user:{id:"user-1",display_name:"Тест MAX",role:"user",login:null,has_password:false}
      };
      return {ok:true,status:200,json:async()=>body};
    },
    console:{error(){}}
  };
  vm.runInNewContext(source,context,{filename:"auth/client.js"});
  await new Promise(resolve=>setImmediate(resolve));
  return {header,dialog:dialogs[0],requests,timers,storage,win,config};
}

async function main(){
  const browser=await render();
  assert.equal(browser.requests.length,0);
  browser.header.authButton.onclick();
  const panel=browser.dialog.children[0];
  assert.match(panel.innerHTML,/Логин и пароль не нужны/);
  assert.match(panel.innerHTML,/Деревья Владивостока/);
  assert.match(panel.innerHTML,/https:\/\/max\.ru\/id2540275814_1_bot/);
  assert.match(panel.innerHTML,/Войти через MAX по коду/);
  assert.match(panel.innerHTML,/У меня уже есть логин и пароль/);
  await panel.querySelector("#vdk-try-max").onclick();
  assert.equal(browser.requests.length,1);
  assert.match(browser.requests[0].url,/\/api\/auth\/device\/start$/);
  assert.equal(panel.querySelector("#vdk-max-pair").querySelector("#vdk-pair-code").textContent,"ABCDEF23");
  assert.equal(browser.timers.length,1);
  browser.config.approved=true;
  browser.timers[0].callback();
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(browser.header.authButton.textContent,"Тест MAX");
  assert.equal(browser.timers[0].active,false);
  assert.equal(browser.storage.size,1);

  let readyCalled=false;
  const signed="auth_date=1730832000&user=%7B%22id%22%3A123%7D&hash=abcdef";
  const mini=await render({bridge:{initData:signed,ready:()=>{readyCalled=true;}}});
  assert.equal(readyCalled,true);
  assert.equal(mini.requests.length,1);
  assert.match(mini.requests[0].url,/\/api\/auth\/max$/);
  assert.equal(JSON.parse(mini.requests[0].opts.body).init_data,signed);
  assert.equal(mini.header.authButton.textContent,"Тест MAX");
  const miniPanel=mini.dialog.children[0];
  const approval=miniPanel.querySelector("#vdk-max-approve");
  assert.match(approval.innerHTML,/Подтвердить вход в браузере/);
  const approveForm=approval.querySelector("form");
  await approveForm.onsubmit({
    preventDefault(){},currentTarget:{elements:{code:{value:"ABCDEF23"}}}
  });
  assert.equal(mini.requests.length,2);
  assert.match(mini.requests[1].url,/\/api\/auth\/device\/approve$/);
  assert.equal(JSON.parse(mini.requests[1].opts.body).init_data,signed);
  assert.match(approval.querySelector("#vdk-approve-status").textContent,/Вход подтверждён/);

  const fallback=await render({hash:"#WebAppData="+encodeURIComponent(signed)+"&WebAppPlatform=web"});
  assert.equal(fallback.requests.length,1);
  assert.equal(JSON.parse(fallback.requests[0].opts.body).init_data,signed);
  assert.match(source,/minlength="8"/);
  assert.doesNotMatch(source,/minlength="12"/);
  console.log("MAX first-time + browser pairing UI checks: 4 passed");
}
main().catch(e=>{console.error(e);process.exitCode=1;});
