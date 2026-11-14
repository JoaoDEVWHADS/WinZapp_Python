"""Exercise emitted presence code on fake requests/pages; no server imports."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from core.contact_presence import merge, response_snapshot
from tests.test_contact_presence_freshness import Owner, PN

API = Path(__file__).resolve().parents[1] / 'client' / 'api'
NODE = shutil.which('node')
pytestmark = pytest.mark.skipif(
    not NODE or not (API/'dist/util/onlinePresenceDiagnostics.js').is_file()
    or not (API/'node_modules/typescript/lib/typescript.js').is_file(),
    reason='Emitted provider and compiler required for offline build acceptance')


def run(world):
    harness = r"""
const fs=require('fs'), path=require('path'), vm=require('vm');
const {api,w}=JSON.parse(process.argv[1]);
const ts=require(path.join(api,'node_modules/typescript/lib/typescript.js'));
function declaration(file,name) {
  const text=fs.readFileSync(path.join(api,'dist/controller',file),'utf8');
  const source=ts.createSourceFile(file,text,ts.ScriptTarget.Latest,true,ts.ScriptKind.JS);
  const fn=source.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text===name);
  if(!fn) throw Error('Missing emitted declaration '+name);
  return text.slice(fn.getStart(source),fn.end);
}
const logs=[], calls=[];
const context=vm.createContext({Date:{now:()=>1000},
  setTimeout:fn=>{if(w.fault==='timeout')queueMicrotask(fn);return 1;},clearTimeout:()=>{}});
function helper(file) {
  context.targetExports={};
  vm.runInContext('(function(exports){\n'+fs.readFileSync(path.join(api,'dist/util',file),'utf8')+'\n})(targetExports)',context);
  return context.targetExports;
}
context._onlinePresenceDiagnostics=helper('onlinePresenceDiagnostics.js');
context._contactPresenceRuntime=helper('contactPresenceRuntime.js');
const name=w.kind==='contact'?'getLastSeen':'setOnlinePresence';
vm.runInContext(declaration(w.kind==='contact'?'deviceController.js':'sessionController.js',name),context);
const window={WPP:{conn:{markAvailable(){}},whatsapp:{
  Stream:{available:w.online}, WidFactory:{createWid:id=>id},
  PresenceStore:{get:()=>({hasData:true,isOnline:w.online,chatstate:{type:w.state,t:1000}})}
}}};
context.req={headers:w.trace?{'x-winzapp-presence-trace':'1','x-winzapp-presence-sequence':'1','x-winzapp-presence-epoch':'1'}:{},
  params:{phone:'123'},body:{isOnline:w.online},logger:{info:s=>logs.push(s),error:()=>{}},client:{
    page:{evaluate:expression=>{
      if(w.fault==='timeout') return new Promise(()=>{});
      if(w.fault==='read') throw Error('PRIVATE_READ');
      return Promise.resolve(vm.runInNewContext(expression,{window}));}},
    setOnlinePresence:async value=>{calls.push(value);if(w.fault==='send')throw Error('PRIVATE_SEND');return true;},
    getLastSeen:async()=>{throw Error('Unexpected legacy request');}
  }};
context.res={code:0,body:null,status(code){this.code=code;return this;},json(body){this.body=body;}};
(async()=>{
  await vm.runInContext(name+'(req,res)',context);
  process.stdout.write(JSON.stringify({code:context.res.code,body:context.res.body,calls,logs}));
})().catch(e=>{process.stderr.write(String(e));process.exitCode=1;});
"""
    result = subprocess.run([NODE,'-e',harness,json.dumps({'api':str(API),'w':world})],
                            capture_output=True,text=True,timeout=10)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.mark.parametrize('state,expected',[('typing','composing'),('recording_audio','recording')])
@pytest.mark.parametrize('online',[False,True])
def test_emitted_contact_controller_to_python_cache_retains_activity(state, expected, online):
    result=run({'kind':'contact','state':state,'online':online})
    assert result['code']==200
    snapshot=response_snapshot(result['body'])
    entry=merge(Owner(),PN,snapshot)
    assert entry['lastKnownPresence']==expected
    assert entry['isOnline'] is online and entry['lastSeen'] is None


@pytest.mark.parametrize('online',[False,True])
@pytest.mark.parametrize('trace',[False,True])
def test_emitted_online_controller_preserves_call_and_optional_trace(online, trace):
    result=run({'kind':'own','online':online,'trace':trace})
    assert result['code']==200 and result['calls']==[online]
    if trace:
        diagnostic=result['body']['diagnostic']
        assert diagnostic['requested'] is online
        assert diagnostic['runtime']['available'] is online
        assert diagnostic['receiverConfirmed'] is False
    else:
        assert 'diagnostic' not in result['body'] and result['logs']==[]


@pytest.mark.parametrize('fault,code,status',[('send',500,None),('read',200,'failed'),('timeout',200,'timeout')])
def test_emitted_controller_keeps_diagnostic_failure_separate(fault, code, status):
    result=run({'kind':'own','online':False,'trace':True,'fault':fault})
    assert result['code']==code and result['calls']==[False]
    if status:
        assert result['body']['diagnostic']['runtime']['status']==status
        assert result['body']['diagnostic']['receiverConfirmed'] is False
    assert 'PRIVATE' not in ' '.join(result['logs'])
