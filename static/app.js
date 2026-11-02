'use strict';
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const escapeHTML=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let book=null, selected=new Set(), catalog=[], imageInDialog=null, previewJob=null, playedPreview=null, jobsFingerprint='';
let toastTimer,activePage='book';
const outputState={audio:{batches:[],chosen:new Set(),request:0,signature:'',busy:false},video:{batches:[],chosen:new Set(),request:0,signature:'',busy:false}};

let selectedJobs=new Set(), latestJobs=[];
const backgroundId=()=>book?(book.background||book.cover):null;
function toast(message){$('#toast').textContent=message;$('#toast').classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('show'),5500)}
async function api(path,body){const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Novelist-TTS':'1'},body:JSON.stringify(body)});const data=await response.json();if(!response.ok)throw Error(data.error||'No se pudo completar la operación.');return data}
function listen(selector,event,handler){$(selector).addEventListener(event,async e=>{try{await handler(e)}catch(error){toast(error.message)}})}
const imageURL=id=>`/api/image?book=${book.id}&image=${encodeURIComponent(id)}&v=${book.images.find(i=>i.id===id)?.rotation||0}`;
const downloadURL=(job,file,inline=false)=>`/api/download?job=${job}&file=${encodeURIComponent(file)}${inline?'&inline=1':''}`;
const names={book:'Libro y capítulos',voices:'Voz y prueba',images:'Ilustraciones',audio:'Crear audio',video:'Crear video',jobs:'Trabajos y descargas'};
function go(page){
 if(!names[page])return;activePage=page;
 $$('.page').forEach(p=>p.classList.toggle('active',p.id===`page-${page}`));
 $$('.nav').forEach(n=>{const current=n.dataset.page===page;n.classList.toggle('active',current);if(current)n.setAttribute('aria-current','page');else n.removeAttribute('aria-current')});
 $('#breadcrumb').textContent='Estudio / '+names[page];
 if(page==='audio'||page==='video')refreshBatches(page).catch(e=>toast(e.message));if(page==='jobs')refreshCache().catch(e=>toast(e.message));
 updateOutputSummaries();if(page==='video')updateVideoPreview();window.scrollTo({top:0,behavior:'smooth'});
}
$$('[data-page]').forEach(b=>b.onclick=()=>go(b.dataset.page));$$('[data-go]').forEach(b=>b.onclick=()=>go(b.dataset.go));
async function refreshLibrary(){const items=await api('/api/library');$('#library').innerHTML=items.length?items.map(b=>`<button class="library-card" data-book="${b.id}">${b.cover?`<img src="/api/image?book=${b.id}&image=${encodeURIComponent(b.cover)}" alt="">`:''}<span><strong>${escapeHTML(b.title)}</strong><small>${b.chapters.length} capítulos · ${escapeHTML(b.author||'Sin autor')}</small></span></button>`).join(''):'<p class="hint">Tus libros importados aparecerán aquí.</p>'}
function useBook(value){book=value;selected=new Set(book.chapters.filter(c=>!c.excluded&&c.text.trim()&&(!Array.isArray(book.settings?.selected_chapters)||book.settings.selected_chapters.includes(c.id))).map(c=>c.id));for(const state of Object.values(outputState)){state.signature='';state.batches=[];state.chosen.clear();state.request++}$('#emptyBook').hidden=true;$('#bookContent').hidden=false;$('#bookTitle').textContent=book.title;$('#bookAuthor').textContent=book.author||'Autor no indicado';$('#chapterCount').textContent=book.chapters.length;$('#imageCount').textContent=book.images.length;$('#rangeTo').value=Math.min(10,book.chapters.length);$('#rangeFrom').max=book.chapters.length;$('#rangeTo').max=book.chapters.length;$('#bookCover').hidden=!book.cover;if(book.cover)$('#bookCover').src=imageURL(book.cover);applySettings(book.settings);renderChapters();renderImages();renderBackgroundControls();updateVideoPreview();go('book');toast('EPUB preparado: '+book.title)}
function renderChapters(){if(!book)return;const query=$('#chapterSearch').value.toLowerCase();$('#chapterList').innerHTML=book.chapters.filter(c=>c.title.toLowerCase().includes(query)||String(c.id)===query).map(c=>`<label class="chapter-row"><input type="checkbox" data-chapter="${c.id}" ${selected.has(c.id)?'checked':''} ${!c.text.trim()?'disabled':''}><span class="chapter-number">${String(c.id).padStart(3,'0')}</span><span class="chapter-title">${escapeHTML(c.title)}</span><small>${c.text.trim()?`${c.characters.toLocaleString('es')} caracteres`:'Sin texto narrable'}${c.image_ids.length?` · ${c.image_ids.length} img`:''}</small></label>`).join('')||'<p class="empty-message">No hay coincidencias.</p>';$('#selectionCount').textContent=selected.size;$('#exportSelection').textContent=`${selected.size} capítulos seleccionados de ${book.chapters.length}. Puedes cambiar la selección en Libro y capítulos.`;updateOutputSummaries()}
async function importFile(file){if(!file)return;if(!file.name.toLowerCase().endsWith('.epub'))throw Error('Selecciona un archivo EPUB.');const b=$('#importButton');b.disabled=true;b.textContent='Importando…';try{const response=await fetch('/api/import?name='+encodeURIComponent(file.name),{method:'POST',headers:{'Content-Type':'application/epub+zip','X-Novelist-TTS':'1'},body:file});const data=await response.json();if(!response.ok)throw Error(data.error);useBook(data);await refreshLibrary()}finally{b.disabled=false;b.textContent='＋ Cargar EPUB';$('#epubFile').value=''}}
listen('#epubFile','change',e=>importFile(e.target.files[0]));$('#importButton').onclick=()=>$('#epubFile').click();$('#emptyBook').onclick=()=>$('#epubFile').click();$('#emptyBook').onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();$('#epubFile').click()}};
$('#emptyBook').ondragover=e=>{e.preventDefault();$('#emptyBook').classList.add('drag')};$('#emptyBook').ondragleave=()=>$('#emptyBook').classList.remove('drag');listen('#emptyBook','drop',async e=>{e.preventDefault();$('#emptyBook').classList.remove('drag');await importFile(e.dataTransfer.files[0])});
listen('#library','click',async e=>{const card=e.target.closest('[data-book]');if(card)useBook(await api('/api/book?id='+card.dataset.book))});listen('#refreshLibrary','click',refreshLibrary);$('#libraryButton').onclick=()=>{go('book');$('#librarySection').scrollIntoView({behavior:'smooth'})};$('#chapterSearch').oninput=renderChapters;
$('#chapterList').onchange=e=>{const id=Number(e.target.dataset.chapter);if(!id)return;if(e.target.checked)selected.add(id);else selected.delete(id);$('#selectionCount').textContent=selected.size;updateOutputSummaries()};$('#selectAll').onclick=()=>{if(book){selected=new Set(book.chapters.filter(c=>c.text.trim()).map(c=>c.id));renderChapters()}};$('#selectNone').onclick=()=>{selected.clear();renderChapters()};$('#selectRange').onclick=()=>{if(!book)return;const from=+$('#rangeFrom').value,to=+$('#rangeTo').value;selected=new Set(book.chapters.filter(c=>c.id>=from&&c.id<=to&&c.text.trim()).map(c=>c.id));renderChapters()};
function engine(){return $('input[name=engine]:checked').value}
function voiceSettings(){return {engine:engine(),voice:$('#voiceSelect').value,rate:+$('#rate').value,pitch:+$('#pitch').value,volume:+$('#volume').value,pause:+$('#pause').value,natural_pauses:$('#naturalPauses').checked,deess:$('#deess').value,neutral_questions:$('#neutralQuestions').checked,supertonic_steps:+$('#supertonicSteps').value,supertonic_variation:+$('#supertonicVariation').value}}
function subtitleSettings(){return {font:$('#subtitleFont').value,size:+$('#subtitleSize').value,color:$('#subtitleColor').value,position:$('#subtitlePosition').value,outline:+$('#subtitleOutline').value,width:+$('#subtitleWidth').value,panel:$('#subtitlePanel').checked}}
function allSettings(){return {voice:voiceSettings(),subtitles:subtitleSettings(),batch_mode:$('#batchMode').value,batch_size:+$('#batchSize').value,formats:selectedFormats(),audio:audioSettings(),video:{batch_mode:$('#videoBatchMode').value,batch_size:+$('#videoBatchSize').value},selected_chapters:[...selected]}}
function applySettings(settings={}){settings={...settings,voice:settings.voice?{...settings.voice}:undefined};$('#supertonicVariation').value=String(settings.voice?.supertonic_variation??0);$('#supertonicSteps').value=String(settings.voice?.supertonic_steps??10);$('#naturalPauses').checked=settings.voice?.natural_pauses!==false;$('#manualPauseField').hidden=$('#naturalPauses').checked;$('#neutralQuestions').checked=settings.voice?.neutral_questions===true;$('#deess').value=settings.voice?.deess??'medium';if(settings.voice){const radio=$(`input[name=engine][value="${settings.voice.engine}"]`);if(radio)radio.checked=true;else{$('input[name=engine][value="edge"]').checked=true;settings.voice={...settings.voice,engine:"edge",voice:"es-MX-JorgeNeural"}};for(const id of ['rate','pitch','volume','pause'])if(settings.voice[id]!=null)$('#'+id).value=settings.voice[id];renderVoiceOptions(settings.voice.voice)}for(const [key,id] of Object.entries({font:'subtitleFont',size:'subtitleSize',color:'subtitleColor',position:'subtitlePosition',outline:'subtitleOutline',width:'subtitleWidth'}))if(settings.subtitles?.[key]!=null)$('#'+id).value=settings.subtitles[key];if(settings.subtitles?.panel!=null)$('#subtitlePanel').checked=settings.subtitles.panel;if(settings.batch_mode)$('#batchMode').value=settings.batch_mode;if(settings.batch_size)$('#batchSize').value=settings.batch_size;restoreAudioSettings(settings);$('#videoBatchMode').value=settings.video?.batch_mode??settings.batch_mode??'10';$('#videoBatchSize').value=settings.video?.batch_size??settings.batch_size??10;$('#videoCustomBatchField').hidden=$('#videoBatchMode').value!=='custom';$('#customBatchField').hidden=$('#batchMode').value!=='custom';updateSliders();updateOutputSummaries()}
async function refreshVoices(force=false){const button=$('#refreshVoices');button.disabled=true;button.textContent='Consultando…';try{const result=await api('/api/voices'+(force?'?refresh=1':''));catalog=result.voices;$('#voiceWarnings').textContent=result.warnings.join('\n')||'Catálogo consultado.';renderVoiceOptions(book?.settings?.voice?.voice||$('#voiceSelect').value)}finally{button.disabled=false;button.textContent='Actualizar voces'}}
function renderVoiceOptions(preferred){const list=catalog.filter(v=>v.engine===engine()&&(!$('#spanishVoicesOnly').checked||v.lang.toLowerCase().startsWith('es')));preferred=preferred||$('#voiceSelect').value;$('#voiceSelect').innerHTML=list.length?list.map(v=>`<option value="${escapeHTML(v.id)}">${escapeHTML(v.name)}${v.installed?'':' · sin descargar'}</option>`).join(''):'<option value="">No se detectaron voces compatibles</option>';if(list.some(v=>v.id===preferred))$('#voiceSelect').value=preferred;else if(engine()==='edge'&&list.some(v=>v.id==='es-MX-DaliaNeural'))$('#voiceSelect').value='es-MX-DaliaNeural';updateVoiceHint()}
function updateVoiceHint(){
 $('#supertonicControls').hidden=engine()!=='supertonic';
 $('#deessField').hidden=!['edge','narrator'].includes(engine());
 $('#neutralQuestionsField').hidden=!['edge','narrator'].includes(engine());
 const voice=catalog.find(v=>v.engine===engine()&&v.id===$('#voiceSelect').value);
 $('#downloadVoice').hidden=!['narrator','supertonic'].includes(engine())||!voice||voice.installed;$('#downloadVoice').textContent=engine()==='narrator'?'↓ Preparar las cuatro voces naturales locales':'↓ Preparar Supertonic 3 y sus diez voces';
 const hints={supertonic:voice?.installed?`Supertonic 3 genera archivos localmente con ${voice.compute||'CPU'}. Español, cinco voces masculinas y cinco femeninas. La primera prueba carga los modelos.${voice.compute_warning?' '+voice.compute_warning:''}`:'Prepara los modelos y las diez voces de Supertonic 3. La descarga inicial requiere internet; después genera audio localmente.',narrator:voice?.installed?'Voz natural local. Usa un paquete compatible guardado en Novelist TTS; funciona sin internet y conserva las voces instaladas de Narrador.':'Pulsa Preparar las cuatro voces naturales locales para descargar los paquetes compatibles. No se modifican las voces instaladas en Windows.',edge:'Voz online. El texto de la narración se envía a Microsoft.',gtts:'Google Traductor: sin clave, requiere internet y permite exportar audio y video. El texto se envía a Google. Es una voz distinta de las voces naturales del modo Lectura de Chrome; los acentos dependen del servicio y pueden cambiar.'};
 $('#voiceHint').textContent=hints[engine()];
 updateOutputSummaries();
 $('#previewButton').textContent='▶ Generar prueba de voz';
}
$$('input[name=engine]').forEach(x=>x.onchange=()=>renderVoiceOptions());$('#voiceSelect').onchange=updateVoiceHint;listen('#refreshVoices','click',()=>refreshVoices(true));
function updateSliders(){for(const id of ['rate','pitch','volume'])$('#'+id+'Value').textContent=(+$('#'+id).value>0&&id!=='volume'?'+':'')+$('#'+id).value+(id==='pitch'?' semitonos':' %')}
for(const id of ['rate','pitch','volume'])$('#'+id).oninput=updateSliders;
listen('#saveSettings','click',async()=>{if(!book)throw Error('Primero carga un EPUB.');book=await api('/api/book/update',{id:book.id,settings:allSettings()});toast('Ajustes guardados.')});
listen('#downloadVoice','click',async()=>{const result=await api(engine()==='narrator'?'/api/install-narrator':engine()==='supertonic'?'/api/install-supertonic':'/api/download-voice',['narrator','supertonic'].includes(engine())?{}:{voice:$('#voiceSelect').value});$('#downloadVoice').disabled=true;toast(result.message)});
$('#useExcerpt').onclick=()=>{if(!book){toast('Primero carga un EPUB.');return}const chapter=book.chapters.find(c=>selected.has(c.id)&&c.text.trim())||book.chapters.find(c=>c.text.trim());if(chapter)$('#previewText').value=chapter.text.slice(0,700)};
listen('#previewButton','click',async()=>{
 const voice=voiceSettings();if(!voice.voice)throw Error('No hay una voz disponible para este motor.');
 const job=await api('/api/preview',{voice,text:$('#previewText').value});previewJob=job.id;$('#previewAudio').hidden=true;$('#previewButton').disabled=true;$('#previewStatus').textContent='Generando prueba…';toast('Prueba añadida a la cola.');
});
function renderImages(){if(!book){$('#imageGrid').innerHTML='<p class="empty-message">Carga un EPUB para ver sus ilustraciones.</p>';return}$('#imageGrid').innerHTML=book.images.map(img=>{const occurrences=book.occurrences.filter(o=>o.image_id===img.id);const tag=img.id===book.cover?'PORTADA':img.id===book.background?'FONDO':img.excluded?'EXCLUIDA':'';return `<article class="image-card ${img.excluded?'excluded':''}"><button class="image-frame" data-image-open="${escapeHTML(img.id)}" aria-label="Revisar ${escapeHTML(img.path)}"><img src="${imageURL(img.id)}" alt="${escapeHTML(img.path.split('/').pop())}" loading="lazy">${tag?`<span class="image-tag">${tag}</span>`:''}</button><div class="image-card-footer"><strong title="${escapeHTML(img.path)}">${escapeHTML(img.path.split('/').pop())}</strong><small>${occurrences.length} apariciones · ${img.rotation}°</small><div class="image-card-actions"><button class="secondary small" data-image-rotate="${escapeHTML(img.id)}">↻ Girar</button><button class="secondary small" data-image-exclude="${escapeHTML(img.id)}">${img.excluded?'Restaurar':'Excluir'}</button></div></div></article>`}).join('')||'<p class="empty-message">Este EPUB no contiene imágenes.</p>'}
async function updateBook(change){book=await api('/api/book/update',{id:book.id,...change});renderImages();renderBackgroundControls();if(book.cover){$('#bookCover').src=imageURL(book.cover);$('#bookCover').hidden=false}updateVideoPreview();if(imageInDialog)renderImageDialog()}
listen('#imageGrid','click',async e=>{const open=e.target.closest('[data-image-open]'),rotate=e.target.closest('[data-image-rotate]'),exclude=e.target.closest('[data-image-exclude]');if(open){imageInDialog=open.dataset.imageOpen;renderImageDialog();$('#imageDialog').showModal()}else if(rotate){const img=book.images.find(i=>i.id===rotate.dataset.imageRotate);await updateBook({image:{id:img.id,rotation:img.rotation+90}})}else if(exclude){const img=book.images.find(i=>i.id===exclude.dataset.imageExclude);await updateBook({image:{id:img.id,excluded:!img.excluded}})}});
function renderImageDialog(){const img=book.images.find(i=>i.id===imageInDialog);$('#dialogTitle').textContent=img.path.split('/').pop();$('#dialogImage').src=imageURL(img.id);$('#imageActions').innerHTML=`<button class="secondary small" data-dialog-action="rotate">↻ Girar 90°</button><button class="secondary small" data-dialog-action="exclude">${img.excluded?'Restaurar':'Excluir del video'}</button><button class="secondary small" data-dialog-action="cover">Usar como portada del audio</button><button class="secondary small" data-dialog-action="background">Usar como fondo / miniatura</button>`;$('#occurrenceList').innerHTML=book.occurrences.filter(o=>o.image_id===img.id).map(o=>{const chapter=book.chapters.find(c=>c.id===o.chapter_id);const context=chapter.text.slice(Math.max(0,o.offset-90),Math.min(chapter.text.length,o.offset+100));return `<div class="occurrence" data-occurrence="${o.id}"><b>${escapeHTML(chapter.title)}</b><p class="hint">…${escapeHTML(context)}…</p><div class="field-row"><label class="field">Duración (s)<input type="number" min="1" max="3600" step="1" data-occ-duration value="${o.duration}"></label><label class="field">Tiempo manual (s)<input type="number" min="0" max="86400" step="0.1" data-occ-time placeholder="Automático" value="${o.time??''}"></label></div><label class="check"><input type="checkbox" data-occ-exclude ${o.excluded?'checked':''}> Excluir esta aparición</label></div>`}).join('')||'<p class="hint">No aparece dentro del texto. Puedes utilizarla como fondo o portada.</p>'}
listen('#imageActions','click',async e=>{const action=e.target.closest('[data-dialog-action]')?.dataset.dialogAction;if(!action)return;const img=book.images.find(i=>i.id===imageInDialog);if(action==='cover'){$('#audioEmbedCover').checked=true;renderAudioCoverControls(img.id);updateAudioControls();book=await api('/api/book/update',{id:book.id,settings:allSettings()});toast('Imagen elegida como portada del audio.');return}await updateBook(action==='rotate'?{image:{id:img.id,rotation:img.rotation+90}}:action==='exclude'?{image:{id:img.id,excluded:!img.excluded}}:{[action]:img.id})});
listen('#occurrenceList','change',async e=>{const parent=e.target.closest('[data-occurrence]');if(!parent)return;const change={id:parent.dataset.occurrence};if(e.target.hasAttribute('data-occ-duration'))change.duration=+e.target.value;if(e.target.hasAttribute('data-occ-time'))change.time=e.target.value===''?null:+e.target.value;if(e.target.hasAttribute('data-occ-exclude'))change.excluded=e.target.checked;await updateBook({occurrence:change})});
$('#closeDialog').onclick=()=>$('#imageDialog').close();$('#imageDialog').onclose=()=>imageInDialog=null;
listen('#applyDuration','click',async()=>{if(!book)throw Error('Primero carga un EPUB.');const duration=+$('#globalDuration').value;if(duration<1||duration>3600)throw Error('Elige una duración entre 1 y 3600 segundos.');await updateBook({all_durations:duration});toast('Duración aplicada a todas las apariciones.')});
$('#uploadImageButton').onclick=()=>{if(!book)return toast('Primero carga un EPUB.');$('#customImage').click()};listen('#customImage','change',async e=>{const file=e.target.files[0];if(!file)return;const response=await fetch('/api/upload-image?book='+book.id,{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Novelist-TTS':'1'},body:file});const data=await response.json();if(!response.ok)throw Error(data.error);book=data;renderImages();renderBackgroundControls();updateVideoPreview();toast('Fondo personalizado añadido.');e.target.value=''});
function batchElement(mode,name){return $('#'+(mode==='video'?'video'+name[0].toUpperCase()+name.slice(1):name))}
function batchSize(mode='audio'){return batchElement(mode,'batchMode').value==='custom'?+batchElement(mode,'batchSize').value:+batchElement(mode,'batchMode').value}
async function refreshBatches(mode='audio'){
 const state=outputState[mode],request=++state.request;
 if(!book||!selected.size){state.batches=[];state.chosen.clear();state.signature='';batchElement(mode,'batchList').innerHTML='<p class="empty-message">Elige capítulos en Libro y capítulos para continuar.</p>';updateOutputSummaries();return}
 batchElement(mode,'exportSelection').textContent=`${selected.size} ${selected.size===1?'capítulo seleccionado':'capítulos seleccionados'} de ${book.chapters.length}.`;
 const signature=JSON.stringify([book.id,[...selected].sort((a,b)=>a-b),batchSize(mode)]);
 if(signature===state.signature){updateOutputSummaries();return}
 state.signature='';state.batches=[];state.chosen.clear();updateOutputSummaries();
 batchElement(mode,'batchList').innerHTML='<p class="hint">Preparando los lotes…</p>';
 const result=await api('/api/batches',{book_id:book.id,chapters:[...selected],batch_size:batchSize(mode)});
 if(request!==state.request)return;
 state.batches=result;state.chosen=new Set(result.map((_,i)=>i));state.signature=signature;
 batchElement(mode,'batchList').innerHTML=result.map((b,i)=>`<label class="batch-row"><input type="checkbox" data-batch="${i}" checked><span><b>${escapeHTML(b.title)}</b><small>${b.ids.length} ${b.ids.length===1?'capítulo':'capítulos'} · ${b.characters.toLocaleString('es')} caracteres</small></span><small>Lote ${i+1}</small></label>`).join('');updateOutputSummaries();
}
function updateOutputSummaries(){
 const voice=catalog.find(v=>v.engine===engine()&&v.id===$('#voiceSelect').value);
 $('#projectStatus').textContent=book?book.title:'Sin libro cargado';
 $$('[data-summary-title]').forEach(x=>x.textContent=book?.title||'Primero, elige un libro');
 $$('[data-summary-author]').forEach(x=>x.textContent=book?.author||'Tu próxima historia empieza aquí.');
 $$('[data-summary-cover]').forEach(x=>{const cover=x.closest('#page-audio')?($('#audioEmbedCover').checked?$('#audioCoverSelect').value||book?.cover:null):book?.cover;x.hidden=!cover;if(cover)x.src=imageURL(cover);else x.removeAttribute('src')});
 for(const mode of ['audio','video']){
  const state=outputState[mode],count=[...state.chosen].reduce((n,i)=>n+(state.batches[i]?.ids.length||0),0);
  const button=$(mode==='audio'?'#generateButton':'#generateVideoButton');
  $(mode==='audio'?'#exportVoice':'#videoExportVoice').textContent=voice?.name||'Selecciona una voz';
  batchElement(mode,'exportInfo').textContent=state.batches.length?`${state.chosen.size} ${state.chosen.size===1?'archivo':'archivos'} · ${count} ${count===1?'capítulo':'capítulos'}`:'Elige los capítulos que quieres incluir.';
  $('#'+(mode==='audio'?'page-audio':'page-video')+' [data-summary-selection]').textContent=count;
  button.disabled=!book||!voice?.installed||!state.chosen.size||state.busy;
  button.textContent=state.busy?'Añadiendo a la cola…':mode==='audio'?'Crear audio →':'Crear video →';
 }
 const format=$('input[name=audioFormat]:checked')?.value||'mp3';$('#audioOutputLabel').textContent=`${format.toUpperCase()} · ${$('#audioBitrate').value} kbps`;
 const kbps=+$('#audioBitrate').value;$('#audioBitrateHint').textContent=`Aproximadamente ${(kbps*.45).toLocaleString('es',{maximumFractionDigits:1})} MB por hora, más portada y etiquetas. Es un bitrate de salida: no añade detalle ni naturalidad a la voz. El tamaño real puede variar.`;
}
for(const mode of ['audio','video']){
 batchElement(mode,'batchMode').addEventListener('change',()=>{batchElement(mode,'customBatchField').hidden=batchElement(mode,'batchMode').value!=='custom';refreshBatches(mode).catch(e=>toast(e.message))});
 batchElement(mode,'batchSize').addEventListener('change',()=>refreshBatches(mode).catch(e=>toast(e.message)));
 batchElement(mode,'batchList').onchange=e=>{if(e.target.dataset.batch==null)return;const index=Number(e.target.dataset.batch);if(e.target.checked)outputState[mode].chosen.add(index);else outputState[mode].chosen.delete(index);updateOutputSummaries()};
}
function updateVideoPreview(){if(backgroundId())$('#videoPreview').style.backgroundImage=`url("${imageURL(backgroundId())}")`;else $('#videoPreview').style.backgroundImage='none';const style=subtitleSettings(),preview=$('#subtitlePreview');preview.style.fontFamily=style.font;preview.style.fontSize=`${Math.max(8,Math.round(style.size*($('#videoPreview').clientWidth||640)/1280))}px`;preview.style.color=style.color;preview.style.background=style.panel?'#0009':'transparent';preview.style.textShadow=style.outline?'1px 1px 2px #000':'none';preview.style.top=style.position==='top'?'30px':style.position==='middle'?'50%':'auto';preview.style.bottom=style.position==='bottom'?'12px':'auto';preview.style.transform=style.position==='middle'?'translateY(-50%)':'none'}
for(const id of ['subtitleFont','subtitleSize','subtitleColor','subtitlePosition','subtitleOutline','subtitleWidth','subtitlePanel'])$('#'+id).oninput=updateVideoPreview;
async function createExport(mode){
 const state=outputState[mode];if(state.busy)return;
 if(!book)throw Error('Primero carga un EPUB.');if(!state.chosen.size)throw Error('Elige al menos un lote.');
 const voice=voiceSettings();if(!voice.voice)throw Error('Selecciona una voz disponible.');
 const ids=[...state.chosen].sort((a,b)=>a-b).flatMap(i=>state.batches[i].ids);
 const formats=mode==='audio'?selectedFormats():['mp4'];
 const audio=mode==='audio'?audioSettings():{embed_cover:false,embed_lyrics:false,sidecar_lyrics:false};
 const options={book_id:book.id,chapters:ids,batch_size:batchSize(mode),formats,voice,subtitles:subtitleSettings(),audio};
 state.busy=true;updateOutputSummaries();
 try{book=await api('/api/book/update',{id:book.id,settings:allSettings()});await api('/api/generate',options);toast(mode==='audio'?'Audio añadido a la cola.':'Video añadido a la cola.');go('jobs');await poll()}
 finally{state.busy=false;updateOutputSummaries()}
}
listen('#generateButton','click',()=>createExport('audio'));listen('#generateVideoButton','click',()=>createExport('video'));
$$('[data-save-settings]').forEach(button=>button.addEventListener('click',async()=>{try{if(!book)throw Error('Primero carga un EPUB.');book=await api('/api/book/update',{id:book.id,settings:allSettings()});toast('Ajustes guardados.')}catch(e){toast(e.message)}}));
const statusLabels={queued:'En cola',running:'Generando',done:'Terminado',cancelled:'Cancelado',error:'Error',interrupted:'Interrumpido'};
const jobType=j=>j.preview?'Prueba de voz':j.options?.formats?.includes('mp4')?(j.options.formats.length>1?'Audio y video':'Video'):'Audio';
function durationLabel(seconds){const n=Math.max(0,Math.floor(seconds));return n>=3600?`${Math.floor(n/3600)} h ${Math.floor(n%3600/60)} min ${n%60} s`:n>=60?`${Math.floor(n/60)} min ${n%60} s`:`${n} s`}
function jobTiming(j,now=Date.now()/1000){
 if(j.status==='queued')return `<span><b>En cola</b> · ${durationLabel(now-j.created)} esperando</span><span>La estimación comienza al procesar.</span>`;
 const active=j.status==='running',stop=active?now:(j.finished||j.updated);
 const elapsed=j.started&&stop?durationLabel(stop-j.started):'No registrado';
 let remaining=active?'Calculando…':'—',finish='';
 if(active&&Number.isFinite(j.eta_seconds)&&j.eta_seconds>0){const seconds=j.eta_seconds-Math.max(0,now-(j.updated||now));remaining=seconds>0?'≈ '+durationLabel(Math.max(1,seconds)):'Actualizando estimación…';if(seconds>0)finish=` · fin de etapa ≈ ${new Date((now+seconds)*1000).toLocaleTimeString('es',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}`}
 return `<span><b>${active?'Transcurrido':'Duración'}</b> · ${elapsed}</span>${active?`<span><b>Restante estimado</b> · ${remaining}${finish}</span><small>${escapeHTML(j.eta_scope||'Preparando estimación…')}. La estimación corresponde a la etapa indicada.</small>`:''}`;
}
function updateJobTimers(){const now=Date.now()/1000;$$('[data-job-timing]').forEach(node=>{const job=latestJobs.find(j=>j.id===node.dataset.jobTiming);if(job)node.innerHTML=jobTiming(job,now)})}
async function poll(){try{const jobs=await api('/api/jobs');latestJobs=jobs;selectedJobs=new Set([...selectedJobs].filter(id=>jobs.some(j=>j.id===id)));updateJobSelection();$('#jobCount').textContent=jobs.filter(j=>['queued','running'].includes(j.status)).length;const fingerprint=JSON.stringify(jobs);if(fingerprint!==jobsFingerprint){jobsFingerprint=fingerprint;$('#jobs').innerHTML=jobs.map(j=>`<article class="job-card"><div class="job-heading"><label class="job-select"><input type="checkbox" data-job-select="${j.id}" ${selectedJobs.has(j.id)?'checked':''} aria-label="Seleccionar trabajo ${escapeHTML(j.title)}"></label><div><div class="job-title-line"><h2>${escapeHTML(j.title)}</h2><span class="job-kind ${j.preview?'preview':j.options?.formats?.includes('mp4')?'video':'audio'}">${jobType(j)}</span></div><small>${new Date(j.created*1000).toLocaleString('es')} · ${j.preview?'Prueba de voz':`${j.options?.formats?.includes('mp4')?'Video MP4':'Audio · '+(j.options?.formats||[]).join(', ').toUpperCase()} · ${j.options?.batch_size||'Todos'} capítulos por lote`}</small></div><span class="job-status ${j.status}">${statusLabels[j.status]||j.status}</span></div><div class="progress"><span style="width:${j.progress}%"></span></div><p class="job-message">${escapeHTML(j.message?.trim()||(j.status==='error'?'El trabajo terminó sin un mensaje de error. Reinicia la aplicación actualizada y pulsa Reanudar.':''))}</p><div class="job-timing" data-job-timing="${j.id}" aria-live="off">${jobTiming(j)}</div><div class="job-actions"><button class="secondary small danger" data-delete-job="${j.id}" ${j.delete_requested?'disabled':''}>${j.delete_requested?'Eliminando…':'Eliminar trabajo'}</button>${['running','queued'].includes(j.status)?`<button class="secondary small" data-cancel="${j.id}">Cancelar</button>`:''}${['error','cancelled','interrupted'].includes(j.status)?`<button class="secondary small" data-resume="${j.id}">Reanudar</button>`:''}${j.files.map(f=>`<a class="download-link ${f.name.endsWith('.zip')?'zip':''}" href="${downloadURL(j.id,f.path)}">↓ ${escapeHTML(f.name)}</a>`).join('')}</div></article>`).join('')||'<div class="panel empty-message">Aún no hay trabajos. Prueba una voz o prepara tu primera exportación.</div>'}if(previewJob&&!jobs.some(j=>j.id===previewJob)){previewJob=null;$('#previewButton').disabled=false;$('#previewAudio').hidden=true;$('#previewStatus').textContent='La prueba se eliminó.'}if(previewJob){const job=jobs.find(j=>j.id===previewJob);if(job){$('#previewStatus').textContent=job.message;if(['done','error','cancelled'].includes(job.status))$('#previewButton').disabled=false;if(job.status==='done'&&playedPreview!==job.id){$('#previewAudio').src=downloadURL(job.id,'prueba.wav',true);$('#previewAudio').hidden=false;playedPreview=job.id}}}const model=await api('/api/model-status');if(model.status==='running'){$('#downloadVoice').disabled=true;$('#voiceHint').textContent=model.message}else if($('#downloadVoice').disabled){$('#downloadVoice').disabled=false;toast(model.message);if(model.status==='done')await refreshVoices()}}catch(error){console.warn(error)}}
listen('#jobs','click',async e=>{const cancel=e.target.closest('[data-cancel]'),resume=e.target.closest('[data-resume]');if(cancel)await api('/api/cancel',{job:cancel.dataset.cancel});if(resume){await api('/api/resume',{job:resume.dataset.resume});toast('Trabajo reanudado con los ajustes guardados.')}await poll()});
refreshLibrary().catch(e=>toast(e.message));refreshVoices().catch(e=>toast(e.message));renderImages();poll();setInterval(poll,2000);setInterval(updateJobTimers,1000);updateVideoPreview();

function renderBackgroundControls(){
 renderAudioCoverControls();
 const select=$('#backgroundSelect');if(!book){select.innerHTML='<option value="">Portada del EPUB (predeterminado)</option>';return}
 select.innerHTML='<option value="">Portada del EPUB (predeterminado)</option>'+book.images.map(i=>`<option value="${escapeHTML(i.id)}">${escapeHTML(i.path.split('/').pop())}${i.id===book.cover?' · portada':''}</option>`).join('');
 select.value=book.background||'';
}
listen('#backgroundSelect','change',async e=>{if(!book)throw Error('Primero carga un EPUB.');await updateBook({background:e.target.value||null})});
listen('#resetBackground','click',async()=>{if(!book)throw Error('Primero carga un EPUB.');await updateBook({background:null});toast('El video utilizará la portada del EPUB.')});
$('#exportUploadBackground').onclick=()=>{if(!book)return toast('Primero carga un EPUB.');$('#customImage').click()};
$('#spanishVoicesOnly').onchange=()=>renderVoiceOptions();
function updateJobSelection(){
 $('#selectedJobsCount').textContent=selectedJobs.size+' seleccionados';$('#deleteSelectedJobs').disabled=!selectedJobs.size;
 $('#deleteAllJobs').disabled=!latestJobs.length;$('#selectAllJobs').checked=latestJobs.length>0&&selectedJobs.size===latestJobs.length;
 $('#selectAllJobs').indeterminate=selectedJobs.size>0&&selectedJobs.size<latestJobs.length;
}
$('#jobs').addEventListener('change',e=>{const id=e.target.dataset.jobSelect;if(!id)return;if(e.target.checked)selectedJobs.add(id);else selectedJobs.delete(id);updateJobSelection()});
$('#selectAllJobs').onchange=e=>{selectedJobs=e.target.checked?new Set(latestJobs.map(j=>j.id)):new Set();jobsFingerprint='';poll()};
async function removeJobs(ids,all=false){
 const count=all?latestJobs.length:ids.length;if(!count)return;
 if(!window.confirm(`¿Eliminar ${count} trabajo(s) y sus archivos generados? Los trabajos activos se cancelarán. Tus libros y voces se conservarán.`))return;
 await api('/api/jobs/delete',all?{all:true}:{jobs:ids});ids.forEach(id=>selectedJobs.delete(id));if(all)selectedJobs.clear();jobsFingerprint='';await poll();toast('Trabajos eliminados; los activos se borran al terminar de cancelarse.');
}
listen('#jobs','click',async e=>{const button=e.target.closest('[data-delete-job]');if(button)await removeJobs([button.dataset.deleteJob])});
listen('#deleteSelectedJobs','click',()=>removeJobs([...selectedJobs]));
listen('#deleteAllJobs','click',()=>removeJobs([],true));

const audioRates={mp3:[64,96,128,192,256,320],m4a:[48,64,96,128,192,256],opus:[24,32,48,64,96,128]};
function selectedFormats(){return [$('input[name=audioFormat]:checked')?.value||'mp3']}
function audioSettings(){return {bitrate:+$('#audioBitrate').value,embed_lyrics:$('#audioEmbedLyrics').checked,embed_cover:$('#audioEmbedCover').checked,sidecar_lyrics:$('#audioSidecarLyrics').checked,cover_image:$('#audioCoverSelect').value||null}}
function updateAudioControls(preferred){
 const format=$('input[name=audioFormat]:checked')?.value||'mp3';const bitrate=preferred??+$('#audioBitrate').value;
 const choices=audioRates[format]||audioRates.mp3;$('#audioBitrate').innerHTML=choices.map(n=>`<option value="${n}">${n} kbps${n===({mp3:96,m4a:96,opus:48}[format])?' · Equilibrado para voz':''}</option>`).join('');
 $('#audioBitrate').value=String(choices.includes(bitrate)?bitrate:format==='opus'?48:96);
 $('#audioCoverControls').hidden=!$('#audioEmbedCover').checked;
 updateAudioCoverPreview();
}
function renderAudioCoverControls(preferred){
 const select=$('#audioCoverSelect');preferred=preferred??select.value;
 select.innerHTML='<option value="">Portada del EPUB</option>'+(book?.images||[]).map(i=>`<option value="${escapeHTML(i.id)}">${escapeHTML(i.path.split('/').pop())}</option>`).join('');
 select.value=(book?.images||[]).some(i=>i.id===preferred)?preferred:'';updateAudioCoverPreview();
}
function updateAudioCoverPreview(){const id=$('#audioCoverSelect').value||book?.cover;const preview=$('#audioCoverPreview');preview.hidden=!id;if(id)preview.src=imageURL(id);else preview.removeAttribute('src');updateOutputSummaries()}
function restoreAudioSettings(settings){
 const formats=settings.formats||['mp3'];const chosen=formats.find(f=>['mp3','m4a','opus'].includes(f))||'mp3';
 $$('input[name=audioFormat]').forEach(x=>x.checked=x.value===chosen);
 const audio=settings.audio||{};for(const [key,id] of Object.entries({embed_lyrics:'audioEmbedLyrics',embed_cover:'audioEmbedCover',sidecar_lyrics:'audioSidecarLyrics'}))$('#'+id).checked=audio[key]!==false;
 renderAudioCoverControls(audio.cover_image||'');updateAudioControls(audio.bitrate??(chosen==='opus'?48:96));
}
$$('input[name=audioFormat]').forEach(x=>x.onchange=()=>updateAudioControls());
$('#audioEmbedCover').onchange=()=>updateAudioControls();$('#audioCoverSelect').onchange=updateAudioCoverPreview;
$('#resetAudioCover').onclick=()=>{renderAudioCoverControls('');toast('Se usará la portada del EPUB para el audio.')};
$('#uploadAudioCover').onclick=()=>{if(!book)return toast('Primero carga un EPUB.');$('#audioCoverFile').click()};
listen('#audioCoverFile','change',async e=>{const file=e.target.files[0];if(!file)return;try{if(!book)throw Error('Primero carga un EPUB.');const response=await fetch('/api/upload-image?book='+book.id+'&target=audio-cover',{method:'POST',headers:{'Content-Type':'application/octet-stream','X-Novelist-TTS':'1'},body:file});const data=await response.json();if(!response.ok)throw Error(data.error||'No se pudo cargar la imagen.');book=data;const id=book.images[book.images.length-1].id;renderImages();renderBackgroundControls();renderAudioCoverControls(id);updateVideoPreview();toast('Imagen elegida como portada del audio.')}finally{e.target.value=''}});
updateAudioControls();

$('#audioBitrate').addEventListener('change',updateOutputSummaries);

window.addEventListener('resize',()=>{if(activePage==='video')updateVideoPreview()});

listen('#naturalPauses','change',()=>{$('#manualPauseField').hidden=$('#naturalPauses').checked});

let cacheBusy=false,cacheStatus=null;
function storageLabel(bytes){let size=Math.max(0,bytes||0),unit=0;const units=['B','KB','MB','GB','TB'];while(size>=1000&&unit<units.length-1){size/=1000;unit++}return size.toLocaleString('es',{maximumFractionDigits:1})+' '+units[unit]}
function renderCacheStatus(){
 $('#cachePanel').setAttribute('aria-busy',String(cacheBusy));$('#refreshCache').disabled=cacheBusy;$('#clearCache').disabled=cacheBusy||!cacheStatus?.deletable_files;
 if(!cacheStatus)return;
 $('#cacheSummary').textContent=storageLabel(cacheStatus.total_bytes)+' en caché · '+(cacheStatus.files||0).toLocaleString('es')+' archivos';
 $('#cacheDetail').textContent=storageLabel(cacheStatus.deletable_bytes)+' disponibles para limpiar.'+(cacheStatus.protected_bytes?' '+storageLabel(cacheStatus.protected_bytes)+' protegidos por trabajos activos o en cola.':'');
}
async function refreshCache(){
 if(cacheBusy)return;cacheBusy=true;renderCacheStatus();
 try{cacheStatus=await api('/api/cache')}
 catch(error){cacheStatus=null;$('#cacheSummary').textContent='No se pudo consultar la caché.';throw error}
 finally{cacheBusy=false;renderCacheStatus()}
}
listen('#refreshCache','click',refreshCache);
listen('#clearCache','click',async()=>{
 if(cacheBusy)return;await refreshCache();if(!cacheStatus?.deletable_files)return;
 if(!window.confirm(`¿Liberar ${storageLabel(cacheStatus.deletable_bytes)} de fragmentos guardados? Se tendrán que generar de nuevo en futuras conversiones. Los libros en conversión, las voces y los archivos exportados se conservan.`))return;
 cacheBusy=true;renderCacheStatus();
 try{const result=await api('/api/cache/clear',{});cacheStatus=result;toast('Caché limpiada: '+storageLabel(result.freed_bytes)+' liberados.'+(result.failed_files?' '+result.failed_files+' archivos no se pudieron borrar.':''))}
 finally{cacheBusy=false;renderCacheStatus()}
});
