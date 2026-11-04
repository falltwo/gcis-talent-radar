'use strict';
// Ordinary HTML controls: options stay inside the page, including in screenshots.
(() => {
 const controls=new Map();let opened=null;
 function close(){if(!opened)return;opened.list.hidden=true;opened.button.setAttribute('aria-expanded','false');opened.button.removeAttribute('aria-activedescendant');opened=null;}
 function highlight(control,index){const options=[...control.select.options];control.active=Math.max(0,Math.min(options.length-1,index));control.items.forEach((item,i)=>item.classList.toggle('active',i===control.active));control.button.setAttribute('aria-activedescendant',control.items[control.active].id);control.items[control.active].scrollIntoView({block:'nearest'});}
 function open(control){close();opened=control;const rect=control.button.getBoundingClientRect(),spaceBelow=innerHeight-rect.bottom-8,spaceAbove=rect.top-8;const above=spaceBelow<180&&spaceAbove>spaceBelow;control.list.style.width=rect.width+'px';control.list.style.left=Math.max(8,Math.min(rect.left,innerWidth-rect.width-8))+'px';control.list.style.maxHeight=Math.min(280,above?spaceAbove:spaceBelow)+'px';control.list.style.top=above?'auto':rect.bottom+4+'px';control.list.style.bottom=above?innerHeight-rect.top+4+'px':'auto';control.list.hidden=false;control.button.setAttribute('aria-expanded','true');highlight(control,control.select.selectedIndex);}
 function choose(control,index){if(control.select.disabled||control.select.options[index].disabled)return;control.select.selectedIndex=index;control.select.dispatchEvent(new Event('input',{bubbles:true}));control.select.dispatchEvent(new Event('change',{bubbles:true}));sync(control);close();control.button.focus();}
 function sync(control){const text=control.select.selectedOptions[0]?.textContent||'請選擇';if(control.value.textContent!==text)control.value.textContent=text;control.button.disabled=control.select.disabled;control.items.forEach((item,i)=>item.setAttribute('aria-selected',String(i===control.select.selectedIndex)));}
 function enhance(select){
  if(controls.has(select)){sync(controls.get(select));return;}
  const button=document.createElement('button'),value=document.createElement('span'),list=document.createElement('div');
  button.type='button';button.className='web-select';button.id=select.id+'-control';button.setAttribute('role','combobox');button.setAttribute('aria-haspopup','listbox');button.setAttribute('aria-expanded','false');button.setAttribute('aria-controls',select.id+'-options');
  const label=document.querySelector('label[for="'+CSS.escape(select.id)+'"]');if(label){label.htmlFor=button.id;button.setAttribute('aria-label',label.textContent.trim());}else button.setAttribute('aria-label',select.getAttribute('aria-label')||select.name||'選擇項目');
  button.append(value);const arrow=document.createElementNS('http://www.w3.org/2000/svg','svg');arrow.setAttribute('viewBox','0 0 16 16');arrow.setAttribute('aria-hidden','true');arrow.innerHTML='<path d="m4 6 4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.5"/>';button.append(arrow);
  list.id=select.id+'-options';list.className='web-select-options';list.setAttribute('role','listbox');list.setAttribute('aria-label',button.getAttribute('aria-label'));list.hidden=true;
  const control={select,button,value,list,items:[],active:select.selectedIndex};
  [...select.options].forEach((option,i)=>{const item=document.createElement('button');item.type='button';item.tabIndex=-1;item.id=list.id+'-'+i;item.setAttribute('role','option');item.textContent=option.textContent;item.disabled=option.disabled;item.addEventListener('click',()=>choose(control,i));list.append(item);control.items.push(item);});
  select.hidden=true;select.after(button);document.body.append(list);controls.set(select,control);sync(control);
  button.addEventListener('click',()=>opened===control?close():open(control));
  button.addEventListener('keydown',event=>{
   const key=event.key;
   if(['ArrowDown','ArrowUp','Home','End'].includes(key)){event.preventDefault();const wasOpen=opened===control;if(!wasOpen)open(control);const next=key==='Home'?0:key==='End'?control.items.length-1:wasOpen?control.active+(key==='ArrowDown'?1:-1):control.active;highlight(control,next);}
   else if(key==='Enter'||key===' '){event.preventDefault();if(opened===control)choose(control,control.active);else open(control);}
   else if(key==='Escape'){event.preventDefault();close();}
   else if(key==='Tab')close();
  });
  select.addEventListener('change',()=>sync(control));
  select.addEventListener('invalid',event=>{event.preventDefault();button.focus();open(control);});
 }
 function refresh(){for(const [select,control] of controls){if(!select.isConnected){if(opened===control)close();control.list.remove();controls.delete(select);}}document.querySelectorAll('select').forEach(enhance);}
 document.addEventListener('pointerdown',event=>{if(opened&&!opened.button.contains(event.target)&&!opened.list.contains(event.target))close();});
 document.addEventListener('reset',()=>setTimeout(refresh,0));
 window.addEventListener('resize',close);window.addEventListener('scroll',event=>{if(opened&&!opened.list.contains(event.target))close();},true);
 new MutationObserver(refresh).observe(document.body,{childList:true,subtree:true});refresh();
})();
