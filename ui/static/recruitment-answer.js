/* Safe, same-page answer reader. User/model content is always rendered as text. */
(function(root){
 'use strict';
 class RecruitmentAnswerDialog{
  constructor(onClose=()=>{}){
   this.dialog=document.createElement('dialog');this.dialog.className='posting-answer-dialog';this.dialog.setAttribute('aria-labelledby','posting-answer-title');
   this.dialog.innerHTML='<header><div><small>AI HR 招募助理</small><h2 id="posting-answer-title">完整回覆</h2></div><button type="button" aria-label="關閉完整回覆">關閉</button></header><p class="posting-answer-question"></p><div class="posting-answer-content" tabindex="0"></div><footer><button type="button">繼續提問</button></footer>';
   document.body.append(this.dialog);this.dialog.querySelectorAll('button').forEach(button=>button.addEventListener('click',()=>this.dialog.close()));this.dialog.addEventListener('close',onClose);
   this.dialog.addEventListener('click',event=>{if(event.target===this.dialog){const r=this.dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)this.dialog.close();}});
  }
  inline(parent,text){for(const [index,part] of text.split(/\*\*(.*?)\*\*/g).entries()){if(index%2){const strong=document.createElement('strong');strong.textContent=part;parent.append(strong);}else parent.append(document.createTextNode(part));}}
  render(parent,text){
   const lines=String(text).split('\n');let index=0;
   const cells=line=>line.trim().replace(/^\||\|$/g,'').split('|').map(s=>s.trim());
   while(index<lines.length){
    const line=lines[index];if(!line.trim()){index++;continue;}
    if(line.includes('|')&&index+1<lines.length&&/^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[index+1])){
     const wrap=document.createElement('div'),table=document.createElement('table'),head=document.createElement('thead'),tr=document.createElement('tr');wrap.className='posting-answer-table';
     for(const cell of cells(line)){const th=document.createElement('th');th.scope='col';this.inline(th,cell);tr.append(th);}head.append(tr);table.append(head);index+=2;
     const body=document.createElement('tbody');while(index<lines.length&&lines[index].includes('|')){const row=document.createElement('tr');for(const cell of cells(lines[index++])){const td=document.createElement('td');this.inline(td,cell);row.append(td);}body.append(row);}table.append(body);wrap.append(table);parent.append(wrap);continue;
    }
    const bullet=line.match(/^\s*(?:[-*]|\d+\.)\s+(.+)/);
    if(bullet){const ordered=/^\s*\d+\./.test(line),list=document.createElement(ordered?'ol':'ul');while(index<lines.length){const item=lines[index].match(ordered?/^\s*\d+\.\s+(.+)/:/^\s*[-*]\s+(.+)/);if(!item)break;const li=document.createElement('li');this.inline(li,item[1]);list.append(li);index++;}parent.append(list);continue;}
    const heading=line.match(/^#{1,3}\s+(.+)/),el=document.createElement(heading?'h3':'p');this.inline(el,heading?heading[1]:line);parent.append(el);index++;
   }
  }
  static renderContent(parent,message){RecruitmentAnswerDialog.prototype.render.call({inline:RecruitmentAnswerDialog.prototype.inline},parent,message);}
  open(question,message,sources=[]){
   this.dialog.querySelector('.posting-answer-question').textContent=question||'助理回覆';const content=this.dialog.querySelector('.posting-answer-content');content.replaceChildren();this.render(content,message);
   const valid=sources.filter(s=>{try{const u=new URL(s.url);return u.protocol==='https:'&&!u.username&&!u.password;}catch{return false;}});
   if(valid.length){const heading=document.createElement('h3'),list=document.createElement('ul');heading.textContent='參考來源';for(const source of valid){const li=document.createElement('li'),a=document.createElement('a');a.textContent=source.title||source.url;a.href=source.url;a.target='_blank';a.rel='noopener noreferrer';li.append(a);list.append(li);}content.append(heading,list);}
   if(!this.dialog.open)this.dialog.showModal();content.scrollTop=0;this.dialog.querySelector('button').focus();
  }
  close(){if(this.dialog.open)this.dialog.close();}
 }
 root.RecruitmentAnswerDialog=RecruitmentAnswerDialog;
})(window);
