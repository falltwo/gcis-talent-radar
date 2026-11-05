/* Two deliberate Enter presses submit; IME commits and Shift+Enter stay local. */
(function(root){
 'use strict';
 function bind(area,send,now=()=>performance.now()){
  let pending=null,composing=false;
  area.addEventListener('compositionstart',()=>{composing=true;pending=null;});
  area.addEventListener('compositionend',()=>{composing=false;pending=null;});
  area.addEventListener('pointerdown',()=>{pending=null;});
  area.addEventListener('keydown',event=>{
   if(composing||event.isComposing||event.keyCode===229){pending=null;return;}
   if(event.key!=='Enter'){pending=null;return;}
   if(event.repeat){event.preventDefault();return;}
   if(event.ctrlKey||event.metaKey){event.preventDefault();pending=null;send();return;}
   if(event.shiftKey||event.altKey){pending=null;return;}
   const time=now();
   if(pending&&time-pending.time<=700&&area.value===pending.expected&&area.selectionStart===pending.caret&&area.selectionEnd===pending.caret){
    event.preventDefault();area.value=pending.original;pending=null;send();return;
   }
   const start=area.selectionStart,end=area.selectionEnd;
   pending={time,original:area.value,expected:area.value.slice(0,start)+'\n'+area.value.slice(end),caret:start+1};
  });
 }
 if(typeof module!=='undefined'&&module.exports)module.exports={bind};else root.RecruitmentComposer={bind};
})(typeof window!=='undefined'?window:globalThis);
