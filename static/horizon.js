(() => {
  const toggle=document.querySelector('#sidebar-toggle');
  toggle?.addEventListener('click',()=>{const collapsed=document.body.classList.toggle('sidebar-collapsed');toggle.setAttribute('aria-expanded',String(!collapsed));toggle.setAttribute('aria-label',collapsed?'Expand sidebar':'Collapse sidebar');});
  const navSearch=document.querySelector('#nav-search');
  navSearch?.addEventListener('input',()=>document.querySelectorAll('[data-nav]').forEach(link=>link.hidden=!link.textContent.toLowerCase().includes(navSearch.value.toLowerCase())));
  document.addEventListener('keydown',e=>{if(e.key==='/'&&!/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)){e.preventDefault();navSearch?.focus();}});
  document.querySelector('#refresh-page')?.addEventListener('click',()=>location.reload());
  document.querySelector('.dismiss-notice')?.addEventListener('click',e=>{const notice=e.target.closest('.notice');notice.classList.add('is-leaving');setTimeout(()=>notice.remove(),200);});
  const orderSearch=document.querySelector('#order-search'),status=document.querySelector('#order-status');
  if(orderSearch&&status){const cards=[...document.querySelectorAll('.order-card')];const empty=document.createElement('p');empty.className='notice';empty.textContent='No orders match the selected filters.';empty.hidden=true;orderSearch.closest('section').appendChild(empty);const filter=()=>{let visible=0;cards.forEach(card=>{card.hidden=!(card.textContent.toLowerCase().includes(orderSearch.value.toLowerCase())&&(status.value==='all'||card.dataset.orderStatus===status.value));if(!card.hidden)visible++;});empty.hidden=visible>0||cards.length===0;};orderSearch.addEventListener('input',filter);status.addEventListener('change',filter);}
  const form=document.querySelector('#order-compose');
  if(!form)return;
  const stages=[...form.querySelectorAll('[data-wizard-step]')],stepLinks=[...document.querySelectorAll('[data-step-link]')];
  if(!stages.length)return;
  const currency=new Intl.NumberFormat('en-IN',{style:'currency',currency:'INR'});
  let step=0;
  const field=name=>form.querySelector(`[name="${name}"]`);
  const selectedLabel=select=>select?.selectedOptions[0]?.textContent.trim()||'—';
  const setText=(id,value)=>{const element=document.getElementById(id);if(element)element.textContent=value;};
  function values(){const partner=field('partner')?.value.trim()||selectedLabel(field('supplier_id')).split(' · ')[0];const rows=[...form.querySelectorAll('.compose-line')].map(row=>{const option=row.querySelector('select').selectedOptions[0];return {id:option?.value||'',name:option?.dataset.productName||'Choose a product',quantity:Number(row.querySelector('input').value)||0,price:Number(option?.dataset.pricePaise)||0};}).filter(row=>row.id);return {partner,warehouse:field('location')?.value||'—',date:field('due_date')?.value||'—',rows};}
  function summary(){const value=values();const total=value.rows.reduce((sum,row)=>sum+row.quantity*row.price,0);setText('summary-partner',value.partner||'—');setText('summary-warehouse',value.warehouse.split(' · ')[0]);setText('summary-date',value.date==='—'?'—':new Date(value.date+'T12:00:00').toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'}));setText('summary-lines',value.rows.length);setText('summary-units',value.rows.reduce((sum,row)=>sum+row.quantity,0));setText('summary-value',currency.format(total/100));setText('review-partner',`${value.partner} · ${value.warehouse} · Due ${value.date}`);const body=document.querySelector('#review-lines');body.replaceChildren();value.rows.forEach(row=>{const tr=document.createElement('tr');[row.name,String(row.quantity),currency.format(row.quantity*row.price/100)].forEach(text=>{const td=document.createElement('td');td.textContent=text;tr.appendChild(td);});body.appendChild(tr);});}
  function show(next){step=next;stages.forEach((stage,i)=>stage.hidden=i!==step);stepLinks.forEach((button,i)=>{button.classList.toggle('current',i===step);button.classList.toggle('complete',i<step);if(i===step)button.setAttribute('aria-current','step');else button.removeAttribute('aria-current');});document.querySelector('#wizard-back').hidden=step===0;document.querySelector('#wizard-cancel').hidden=step!==0;document.querySelector('#wizard-next').hidden=step===2;document.querySelector('#wizard-submit').hidden=step!==2;document.querySelector('#wizard-error').hidden=true;summary();}
  function valid(index){const fields=[...stages[index].querySelectorAll('input,select')];for(const input of fields){if(!input.checkValidity()){input.reportValidity();return false;}}if(index===1){const ids=values().rows.map(row=>row.id);if(new Set(ids).size!==ids.length){const error=document.querySelector('#wizard-error');error.textContent='Use each product once. Combine its quantity into one line.';error.hidden=false;return false;}}return true;}
  function go(target){if(target>step){for(let i=step;i<target;i++){show(i);if(!valid(i))return;}}show(target);}
  document.querySelector('#wizard-next').addEventListener('click',()=>go(Math.min(2,step+1)));
  document.querySelector('#wizard-back').addEventListener('click',()=>go(Math.max(0,step-1)));
  stepLinks.forEach(button=>button.addEventListener('click',()=>go(Number(button.dataset.stepLink))));
  form.addEventListener('input',summary);form.addEventListener('change',summary);form.addEventListener('click',e=>{if(e.target.closest('#add-line,.remove-line'))queueMicrotask(summary);});
  form.addEventListener('submit',event=>{if(step!==2){event.preventDefault();go(2);}});
  show(0);
})();
