'use strict';
const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let topics = [], categories = {}, user = null, view = 'home', category = '', search = '', page = 1, requestId = 0, modalRequest = 0;
let returnPath = '/forum';
let tagCatalog=[],adminSearch='',adminPage=1,modalCleanup=null;
const date = value => new Date(value * 1000).toLocaleDateString('de-DE', {day:'numeric',month:'short',year:'numeric'});
const canWrite = () => !!(user && user.email_verified);
const canEdit = item => canWrite() && (user.admin || user.id === item.user_id);
function avatar(name, hasAvatar, large = false) {
  return `<span class="avatar ${large ? 'profile-avatar' : ''}">${hasAvatar ? `<img src="/api/users/${encodeURIComponent(name)}/avatar" alt="Profilbild von ${esc(name)}">` : esc(name[0]?.toUpperCase() || '?')}</span>`;
}
function authorLink(name, userId, hasAvatar, userTags = []) {
  return userId ? `<a class="author-link" href="/users/${encodeURIComponent(name)}">${avatar(name,hasAvatar)}<span>${esc(name)}</span>${tagBadges(userTags)}</a>` : `<span class="author-link">${avatar(name,false)}<span>${esc(name)}</span></span>`;
}
function postImages(post) {
  if (!post.images?.length) return '';
  return `<section class="post-image-section" aria-label="Bilder zum Beitrag"><p class="form-note">${post.images.length} ${post.images.length===1 ? 'Bild' : 'Bilder'} · Zum Vergrößern öffnen</p><div class="post-image-grid">${post.images.map((image,index) => `<a href="${esc(image.url)}" target="_blank" rel="noopener" class="post-image"><img src="${esc(image.url)}" width="${image.width}" height="${image.height}" loading="lazy" alt="Bild ${index+1} zu ${esc(post.title)}"><span>Bild vergrößern ↗</span></a>`).join('')}</div></section>`;
}
function tagBadges(tags = []) {
  return tags.map(t => `<span class="tag-badge tag-${esc(t.color)}">${esc(t.name)}</span>`).join('');
}
async function loadTags() {tagCatalog=(await api('tags')).tags;}
function tagChoices(kind, selected = []) {
  const ids=new Set(selected.map(t => t.id));
  return `<div class="tag-choices">${tagCatalog.filter(t => t.kind===kind).map(t => `<label><input type="checkbox" name="tag_ids" value="${t.id}" ${ids.has(t.id) ? 'checked' : ''}>${tagBadges([t])}</label>`).join('') || '<p class="form-note">Noch keine Tags angelegt.</p>'}</div>`;
}
async function api(path, method = 'GET', data) {
  const options = {method, headers:{}};
  if (method !== 'GET') {options.headers = {'Content-Type':'application/json','X-Requested-With':'Steckerrein'}; options.body = JSON.stringify(data || {});}
  let response;
  try {response = await fetch('/api/' + path, options);} catch {throw new Error('Verbindung fehlgeschlagen. Bitte versuche es erneut.');}
  let result;
  try {result = await response.json();} catch {throw new Error('Der Server ist gerade nicht erreichbar.');}
  if (!response.ok) {const error = new Error(result.error || 'Die Anfrage ist fehlgeschlagen.'); error.code = result.code; throw error;}
  return result;
}
function toast(message) {
  $('#toast').textContent = message; $('#toast').style.display = 'block';
  clearTimeout(toast.timer); toast.timer = setTimeout(() => $('#toast').style.display = 'none', 5000);
}
function account() {
  $('#admin-nav')?.remove();
  if (user?.admin) document.querySelector('nav[aria-label="Hauptnavigation"]').insertAdjacentHTML('beforeend','<a id="admin-nav" href="/admin" data-nav="admin">Adminbereich</a>');
  $('#account').innerHTML = user ? `<a class="account-profile" href="/users/${encodeURIComponent(user.username)}" aria-label="Mein Profil">${avatar(user.username,user.has_avatar)}<span class="account-name">${esc(user.username)}${user.admin ? '<small class="role-label">Administrator</small>' : ''}</span></a><button class="plain" data-action="logout">Abmelden</button>` : '<button class="plain" data-action="login">Anmelden</button><button class="button secondary small" data-action="register">Mitmachen →</button>';
  for (const button of document.querySelectorAll('[data-action="compose"]')) button.hidden = !canWrite();
}
function openModal(html) {
  if (modalCleanup) {modalCleanup();modalCleanup=null;}
  modalRequest++; $('#modal-content').innerHTML = html;
  if (!$('#modal').open) $('#modal').showModal();
  $('#modal').scrollTop = 0;
}
function closeModal(changePath = true) {
  if (modalCleanup) {modalCleanup();modalCleanup=null;}
  modalRequest++; $('#modal').close();
  if (changePath && location.pathname.startsWith('/posts/')) navigate(returnPath);
}
function navigate(path) {history.pushState({},'',path); route();}
function topicTrail(slug) {
  const trail=[],seen=new Set();
  while (slug && !seen.has(slug)) {
    seen.add(slug);const topic=topics.find(t => t.slug===slug);if (!topic) break;
    trail.unshift(topic);slug=topic.parent_slug;
  }
  return trail;
}
function topicLabel(topic) {return topicTrail(topic.slug).map(t => t.name).join(' / ');}
function orderedTopics() {
  const ordered=[];
  const visit=parent => {for (const t of topics.filter(t => t.parent_slug===parent)) {ordered.push(t);visit(t.slug);}};
  visit(null);return ordered;
}
function boardCards(boards) {
  return boards.length ? `<div class="board-grid">${boards.map(t => `<article class="board-card"><span class="board-icon" aria-hidden="true">▤</span><h3><a href="/forum/${t.slug}">${esc(t.name)}</a></h3><p>${esc(t.description)}</p><span>${t.children} Unterthemen · ${t.posts} Beiträge <b aria-hidden="true">→</b></span><small class="board-policy">${t.allow_posts ? 'Beiträge erlaubt' : 'Keine neuen Beiträge'} · ${t.allow_replies ? 'Antworten erlaubt' : 'Antworten gesperrt'}</small>${canWrite() && user.admin ? `<div class="board-actions"><button class="text-link" data-action="edit-topic" data-topic="${t.slug}" aria-label="${esc(t.name)} bearbeiten">Bearbeiten</button><button class="delete-button" data-action="delete-topic" data-topic="${t.slug}" aria-label="${esc(t.name)} löschen">Löschen</button></div>` : ''}</article>`).join('')}</div>` : '';
}
async function loadTopics() {
  topics = (await api('topics')).topics;
  categories = Object.fromEntries(topics.map(t => [t.slug,t.name]));
  const html = orderedTopics().map(t => `<a href="/forum/${t.slug}" class="category-link" style="--depth:${topicTrail(t.slug).length-1}" data-category="${t.slug}"><i></i>${esc(t.name)}</a>`).join('');
  $('#categories').innerHTML = html; $('#mobile-categories').innerHTML = html;
}
function mayCompose() {
  if (!canWrite()) return false;
  if (view==='blog') return !!user.admin;
  if (view==='forum') return !!topics.find(t => t.slug===category)?.allow_posts;
  return topics.some(t => t.allow_posts);
}
function controls() {
  const area=$('#feed-heading-actions');
  if (area) area.innerHTML=`${canWrite() && user.admin && view==='forum' ? '<button class="button secondary small" data-action="new-topic">＋ '+(category ? 'Unterthema' : 'Themenbereich')+'</button>' : ''}${canWrite() && user.admin && view==='forum' && categories[category] ? '<button class="button secondary small" data-action="edit-topic">Bereich bearbeiten</button><button class="button secondary small" data-action="delete-topic">Bereich löschen</button>' : ''}${mayCompose() ? '<button class="button primary small" data-action="compose">＋ '+(view==='blog' ? 'Blogartikel' : 'Neuer Beitrag')+'</button>' : ''}`;
  for (const button of document.querySelectorAll('[data-action="compose"]')) button.hidden=!mayCompose();
}
async function renderFeed() {
  const id = ++requestId;
  for (const node of document.querySelectorAll('[data-nav],[data-side],[data-filter]')) node.classList.toggle('active',(node.dataset.nav || node.dataset.side || node.dataset.filter) === view);
  for (const node of document.querySelectorAll('[data-category]')) node.classList.toggle('active',node.dataset.category === category);
  $('#hero').hidden = view !== 'home';
  document.title = (view === 'forum' ? (categories[category] || 'Forum') : view === 'blog' ? 'Blog' : 'Ideen verbinden.') + ' – steckerrein.de';
  $('#feed-title').innerHTML = esc(view === 'forum' ? (categories[category] || 'Das Forum') : view === 'blog' ? 'Gedanken & Anleitungen' : 'Frische Impulse') + '<span>.</span>';
  $('#feed-kicker').textContent = view === 'forum' ? 'THEMEN ENTDECKEN. WISSEN TEILEN.' : view === 'blog' ? 'NEUES AUS DER WERKSTATT' : 'WISSEN WÄCHST, WENN MAN ES TEILT';
  controls();
  $('#filter-info').innerHTML = category ? `<nav class="breadcrumbs" aria-label="Themenpfad"><a href="/forum">Forum</a>${topicTrail(category).map(t => `<span aria-hidden="true">/</span><a href="/forum/${t.slug}">${esc(t.name)}</a>`).join('')}</nav>` : '';
  $('#posts').innerHTML = '<div class="empty">Beiträge werden geladen …</div>';
  $('#pagination').innerHTML = '';
  const params = new URLSearchParams({page});
  if (view !== 'home') params.set('kind',view);
  if (category) params.set('category',category);
  if (search) params.set('q',search);
  try {
    const result = await api('posts?' + params);
    if (id !== requestId) return;
    if (view === 'forum' && !category && !search) {
      $('#posts').innerHTML = `<p class="forum-intro">Wähle ein Oberthema und anschließend ein Unterthema. Verifizierte Mitglieder schreiben in den dafür freigegebenen Bereichen.</p>${boardCards(topics.filter(t => !t.parent_slug)) || '<p class="empty">Noch keine Themenbereiche vorhanden.</p>'}`;
    } else {
      const current=topics.find(t => t.slug===category);
      const subtopics=view==='forum' && category && !search ? boardCards(topics.filter(t => t.parent_slug===category)) : '';
      const intro=current && view==='forum' ? `<p class="forum-intro">${esc(current.description)}${current.allow_posts ? '' : current.allow_replies ? '<br>Neue Beiträge sind gesperrt. Du kannst auf vorhandene Beiträge antworten.' : '<br>Neue Beiträge und Antworten sind gesperrt. Wähle ein freigegebenes Unterthema.'}</p>` : '';
      $('#posts').innerHTML = intro+subtopics+(result.posts.length ? result.posts.map(post => `<article class="post-card"><div class="post-meta"><span class="badge ${post.kind}">${post.kind === 'blog' ? 'AUS DEM BLOG' : 'BEITRAG'}</span><span class="category-text">${esc(categories[post.category])}</span></div><div class="post-tags">${tagBadges(post.tags)}</div><h3><a href="/posts/${post.id}">${esc(post.title)}</a></h3><p>${esc(post.excerpt)}</p>${post.images?.length ? `<div class="feed-image-preview"><img src="${esc(post.images[0].url)}" alt="Bild zu ${esc(post.title)}" loading="lazy"><span>${post.images.length} ${post.images.length===1 ? 'Bild' : 'Bilder'}</span></div>` : ''}<div class="post-bottom">${authorLink(post.author,post.user_id,post.has_avatar,post.author_tags)}<span>·</span><time datetime="${new Date(post.created*1000).toISOString()}">${date(post.created)}</time><span class="reply-count">▤ &nbsp; ${post.comments} ${post.comments === 1 ? 'Antwort' : 'Antworten'}</span></div><span class="card-arrow" aria-hidden="true">→</span></article>`).join('') : `<div class="empty"><h3>${search ? 'Noch kein Treffer.' : 'Noch keine Beiträge.'}</h3><p>${search ? 'Versuche einen anderen Suchbegriff.' : mayCompose() ? 'Erstelle den ersten Beitrag in diesem Themenbereich.' : canWrite() ? 'Beiträge werden in den freigegebenen Unterthemen erstellt.' : 'Melde dich mit einer bestätigten E-Mail-Adresse an, um mitzumachen.'}</p>${mayCompose() ? '<button class="button secondary small" data-action="compose">Beitrag erstellen →</button>' : !canWrite() ? '<button class="button secondary small" data-action="login">Anmelden</button>' : ''}</div>`);
      if (result.total > 12) $('#pagination').innerHTML = `<button class="plain" data-action="previous" ${page === 1 ? 'disabled' : ''}>← Zurück</button><span>${page} / ${Math.ceil(result.total/12)}</span><button class="plain" data-action="next" ${page*12 >= result.total ? 'disabled' : ''}>Weiter →</button>`;
    }
    const s = result.stats;
    $('#stats').innerHTML = `<span><strong>${s.members}</strong> Mitglieder</span><span><strong>${s.topics}</strong> Forenbeiträge</span><span><strong>${s.articles}</strong> Blogartikel</span><span><span class="status-dot"></span> &nbsp; Raum für deine Ideen</span>`;
  } catch(error) {
    if (id === requestId) $('#posts').innerHTML = `<div class="empty"><p>${esc(error.message)}</p><button class="button secondary small" data-action="retry">Erneut versuchen</button></div>`;
  }
}
function verificationNotice(message) {
  openModal(`<div class="eyebrow">FAST GESCHAFFT</div><h2 class="modal-title">Prüfe dein E-Mail-Postfach.</h2><p class="modal-subtitle">${esc(message)}</p><p class="form-note">Der Bestätigungslink ist 24 Stunden gültig. Erst nach der Bestätigung kannst du dich anmelden und Beiträge verfassen.</p><div class="confirm-row"><button class="button primary" data-action="login">Zur Anmeldung</button><button class="button secondary" data-action="resend">Neue Bestätigung</button></div>`);
}
function auth(mode = 'login', identifier = '') {
  const register = mode === 'register', resend = mode === 'resend';
  openModal(`<div class="eyebrow">DEIN PLATZ IN DER COMMUNITY</div><h2 class="modal-title">${register ? 'Schön, dass du mitmachst.' : resend ? 'E-Mail-Adresse bestätigen.' : 'Willkommen zurück.'}</h2><p class="modal-subtitle">${resend ? 'Bestätigung erneut senden oder bei einem bestehenden Konto die E-Mail-Adresse ergänzen.' : register ? 'Bestätige deine E-Mail-Adresse und werde Teil der Community.' : 'Melde dich mit E-Mail-Adresse oder Nutzernamen an.'}</p><form class="editor-form" id="auth-form"><label>${register ? 'Nutzername' : 'E-Mail-Adresse oder Nutzername'}<input name="${register ? 'username' : 'identifier'}" value="${esc(identifier)}" required minlength="3" maxlength="${register ? 24 : 254}" ${register ? 'pattern="[A-Za-z0-9_-]+"' : ''} autocomplete="username"></label>${register || resend ? `<label>E-Mail-Adresse${resend ? ' (nur bei einem bisherigen Konto ohne Adresse erforderlich)' : ''}<input name="email" type="email" ${register ? 'required' : ''} maxlength="254" autocomplete="email" placeholder="name@beispiel.de"></label>` : ''}<label>Passwort<input name="password" type="password" required minlength="10" maxlength="128" autocomplete="${register ? 'new-password' : 'current-password'}" placeholder="Mindestens 10 Zeichen"></label>${register ? '<p class="form-note">Dein Nutzername und deine Beiträge sind öffentlich, deine E-Mail-Adresse bleibt privat. Beachte unsere <a href="/datenschutz.html" target="_blank" rel="noopener">Datenschutzhinweise</a>. Eine automatische Passwort-Wiederherstellung gibt es derzeit nicht.</p>' : ''}<p class="form-error" role="alert"></p><button class="button primary" type="submit">${register ? 'Konto erstellen' : resend ? 'Bestätigung senden' : 'Anmelden'} →</button></form><p class="auth-switch">${register ? 'Schon dabei? <button data-action="login">Anmelden</button>' : '<button data-action="register">Konto erstellen</button> · <button data-action="resend">E-Mail bestätigen / erneut senden</button>'}</p>`);
  $('#auth-form').addEventListener('submit',async event => {
    event.preventDefault(); const form = event.currentTarget, button = form.querySelector('[type=submit]'); button.disabled = true;
    const data = Object.fromEntries(new FormData(form));
    try {
      const result = await api(register ? 'register' : resend ? 'request-verification' : 'login','POST',data);
      if (register || resend) {verificationNotice(result.message);return;}
      user = result.user; account(); closeModal(false); toast('Du bist angemeldet.'); await route();
    } catch(error) {
      if (error.code === 'EMAIL_UNVERIFIED') {auth('resend',data.identifier); $('#auth-form .form-error').textContent = error.message;}
      else form.querySelector('.form-error').textContent = error.message;
    } finally {button.disabled = false;}
  });
}
async function compose(post = null) {
  if (!canWrite()) return auth('login');
  try {await loadTags();} catch(error) {return toast(error.message);}
  const kind = post?.kind || (view === 'blog' && user.admin ? 'blog' : 'forum');
  const destinations=orderedTopics().filter(t => kind==='blog' || t.allow_posts || post?.category===t.slug);
  if (!destinations.length) return toast('Es gibt noch keinen Themenbereich, der Beiträge erlaubt.');
  if (!post && view==='forum' && !mayCompose()) return toast('Wähle zuerst ein Unterthema, in dem Beiträge erlaubt sind.');
  openModal(`<div class="eyebrow">WAS BESCHÄFTIGT DICH?</div><h2 class="modal-title">${post ? 'Beitrag bearbeiten.' : kind === 'blog' ? 'Ein neuer Blogartikel.' : 'Dein Beitrag zur Community.'}</h2><form id="post-form" class="editor-form"><input type="hidden" name="kind" value="${kind}"><label>Themenbereich<select name="category" required>${destinations.map(t => `<option value="${t.slug}" ${(post?.category || category) === t.slug ? 'selected' : ''}>${esc(topicLabel(t))}</option>`).join('')}</select></label><label>Titel<input name="title" required minlength="5" maxlength="140" value="${esc(post?.title || '')}" placeholder="Worum geht es?"></label><fieldset class="tag-fieldset"><legend>Tags (optional, höchstens 10)</legend>${tagChoices('post',post?.tags || [])}</fieldset><label for="post-body">Dein Beitrag</label><textarea id="post-body" name="body" required minlength="20" maxlength="15000" rows="8">${esc(post?.body || '')}</textarea><label for="post-photos">Bilder hinzufügen (JPG oder PNG)</label><input id="post-photos" name="photos" type="file" accept="image/jpeg,image/png" multiple><p class="form-note">Bis zu 5 Bilder, jeweils höchstens 5 MB und 16 Megapixel. Bilder werden auf maximal 2560 Pixel Seitenlänge verkleinert und ohne Metadaten gespeichert.</p><div id="image-drafts" class="image-drafts" aria-live="polite"></div><p class="form-note">Beiträge und Bilder sind öffentlich. Bleib freundlich und teile keine Passwörter oder persönlichen Daten Dritter.</p><p class="form-error" role="alert"></p><button class="button primary" type="submit">${post ? 'Änderungen speichern' : 'Beitrag veröffentlichen'} →</button></form>`);
  const formNode=$('#post-form'),editorTicket=modalRequest;
  let pictures=(post?.images || []).map(image => ({token:image.token,preview:image.url}));
  modalCleanup=()=>{for (const picture of pictures) if (picture.preview?.startsWith('blob:')) URL.revokeObjectURL(picture.preview);};
  const renderDrafts=()=>{$('#image-drafts').innerHTML=pictures.map((picture,index)=>`<div class="image-draft"><img src="${esc(picture.preview)}" alt="Bildvorschau ${index+1}"><button type="button" data-remove-image="${index}" aria-label="Bild ${index+1} entfernen">✕</button></div>`).join('');};
  renderDrafts();
  formNode.addEventListener('click',event=>{
    const button=event.target.closest('[data-remove-image]');if(!button)return;
    const index=Number(button.dataset.removeImage),picture=pictures[index];
    if(picture.preview?.startsWith('blob:'))URL.revokeObjectURL(picture.preview);
    pictures.splice(index,1);renderDrafts();
  });
  $('#post-photos').addEventListener('change',async event=>{
    const input=event.currentTarget,files=[...input.files],submit=formNode.querySelector('[type=submit]');submit.disabled=true;input.disabled=true;
    try {
      if(pictures.length+files.length>5)throw new Error('Du kannst höchstens fünf Bilder pro Beitrag hinzufügen.');
      for(const file of files) {
        if(file.size>5*1024*1024)throw new Error('Jedes Bild darf höchstens 5 MB groß sein.');
        if(!['image/jpeg','image/png'].includes(file.type) && !/\.(jpe?g|png)$/i.test(file.name))throw new Error('Bitte wähle JPG- oder PNG-Bilder aus.');
      }
      for(const file of files) {
        const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('Das Bild konnte nicht gelesen werden.'));reader.readAsDataURL(file);});
        if(editorTicket!==modalRequest)return;
        pictures.push({data,preview:URL.createObjectURL(file)});
      }
      if(editorTicket===modalRequest){renderDrafts();formNode.querySelector('.form-error').textContent='';}
    } catch(error) {if(editorTicket===modalRequest)formNode.querySelector('.form-error').textContent=error.message;}
    finally {input.value='';input.disabled=false;submit.disabled=false;}
  });
  $('#post-form').addEventListener('submit',async event => {
    event.preventDefault(); const form = event.currentTarget, button = form.querySelector('[type=submit]'); button.disabled = true;
    try {
      const data=Object.fromEntries(new FormData(form));delete data.photos;data.images=pictures.map(picture=>picture.token ? {token:picture.token} : {data:picture.data});data.tag_ids=new FormData(form).getAll('tag_ids').map(Number);
      const result = await api(post ? 'posts/'+post.id : 'posts',post ? 'PATCH' : 'POST',data);
      const id = post ? post.id : result.id;
      await loadTopics(); closeModal(false); toast(post ? 'Änderungen gespeichert.' : 'Dein Beitrag ist veröffentlicht.');
      if (location.pathname === '/posts/'+id) await showPost(String(id)); else navigate('/posts/'+id);
    } catch(error) {form.querySelector('.form-error').textContent = error.message;} finally {button.disabled = false;}
  });
}
function newTopic(topic = null) {
  if (!canWrite() || !user.admin) return;
  const parents=orderedTopics().filter(t => !topic || !topicTrail(t.slug).some(ancestor => ancestor.slug===topic.slug));
  const parent=topic ? topic.parent_slug : category || null;
  openModal(`<div class="eyebrow">ADMINISTRATION</div><h2 class="modal-title">Themenbereich ${topic ? 'bearbeiten' : 'erstellen'}.</h2><p class="modal-subtitle">${topic ? 'Name und Beschreibung ändern. Beiträge und bestehende Links bleiben erhalten.' : 'Mitglieder können in diesem Bereich eigene Beiträge veröffentlichen.'}</p><form id="topic-form" class="editor-form"><label>Übergeordneter Bereich<select name="parent_slug"><option value="">Keiner – als Oberthema anzeigen</option>${parents.map(t => `<option value="${t.slug}" ${parent===t.slug ? 'selected' : ''}>${esc(topicLabel(t))}</option>`).join('')}</select></label><label class="topic-policy"><input type="checkbox" name="allow_posts" ${topic ? topic.allow_posts ? 'checked' : '' : parent ? 'checked' : ''}> Neue Beiträge in diesem Bereich erlauben</label><label class="topic-policy"><input type="checkbox" name="allow_replies" ${topic ? topic.allow_replies ? 'checked' : '' : parent ? 'checked' : ''}> Antworten auf bestehende Beiträge erlauben</label><p class="form-note">Beide Einstellungen sind unabhängig. Für eine Ankündigung mit Diskussion: neue Beiträge ausschalten, Antworten einschalten. Bestehende Inhalte bleiben erhalten.</p><label>Name<input name="name" required minlength="3" maxlength="80" value="${esc(topic?.name || '')}" placeholder="Zum Beispiel: Heimautomatisierung"></label><label for="topic-description">Beschreibung</label><textarea id="topic-description" name="description" required minlength="10" maxlength="300" rows="3">${esc(topic?.description || '')}</textarea><p class="form-error" role="alert"></p><button type="submit" class="button primary">${topic ? 'Änderungen speichern' : 'Themenbereich erstellen'}</button></form>`);
  $('#topic-form').addEventListener('submit',async event => {
    event.preventDefault(); const form = event.currentTarget, button = form.querySelector('button'); button.disabled = true;
    try {
      const data=Object.fromEntries(new FormData(form));data.parent_slug=data.parent_slug || null;data.allow_posts=form.elements.allow_posts.checked;data.allow_replies=form.elements.allow_replies.checked;
      const result = await api(topic ? 'topics/'+topic.slug : 'topics',topic ? 'PATCH' : 'POST',data);
      await loadTopics(); closeModal(false); navigate('/forum/'+result.slug); toast(topic ? 'Themenbereich aktualisiert.' : 'Themenbereich erstellt.');
    } catch(error) {form.querySelector('.form-error').textContent = error.message;} finally {button.disabled = false;}
  });
}
function deleteTopic(topic) {
  if (!topic || !canWrite() || !user.admin) return;
  if (topic.children) return openModal('<h2 class="modal-title">Bereich enthält Unterthemen.</h2><p class="modal-subtitle">Verschiebe die Unterthemen zuerst über „Bearbeiten“ in einen anderen Bereich oder entferne sie einzeln. So bleiben ihre Struktur und Inhalte erhalten.</p>');
  const targets=orderedTopics().filter(t => t.slug !== topic.slug && t.allow_posts);
  const hasContent=topic.items > 0;
  openModal(`<div class="eyebrow">ADMINISTRATION</div><h2 class="modal-title">Themenbereich löschen?</h2><p class="modal-subtitle">„${esc(topic.name)}“ wird dauerhaft entfernt. ${hasContent ? 'Alle Beiträge, Blogartikel und Antworten bleiben erhalten und werden dem gewählten Zielbereich zugeordnet.' : 'Der Bereich ist leer. Falls zwischenzeitlich Inhalte hinzukommen, wird das Löschen ohne Zielbereich abgelehnt.'}</p><form id="delete-topic-form" class="editor-form">${targets.length ? `<label>Inhalte verschieben nach<select name="move_to" ${hasContent ? 'required' : ''}><option value="">${hasContent ? 'Bitte Zielbereich wählen' : 'Kein Zielbereich (nur leer löschen)'}</option>${targets.map(t => `<option value="${t.slug}">${esc(topicLabel(t))}</option>`).join('')}</select></label>` : hasContent ? '<p class="form-error">Erstelle zuerst einen anderen Themenbereich als Ziel für die vorhandenen Inhalte.</p>' : ''}<p class="form-error" role="alert"></p><div class="confirm-row"><button type="button" class="button secondary" id="cancel-delete-topic">Abbrechen</button><button type="submit" class="button primary" ${hasContent && !targets.length ? 'disabled' : ''}>Themenbereich endgültig löschen</button></div></form>`);
  $('#cancel-delete-topic').onclick = () => closeModal(false);
  $('#delete-topic-form').addEventListener('submit',async event => {
    event.preventDefault(); const form=event.currentTarget, button=form.querySelector('[type=submit]');button.disabled=true;
    const target=new FormData(form).get('move_to');
    try {
      const result=await api('topics/'+topic.slug,'DELETE',target ? {move_to:target} : {});
      await loadTopics();closeModal(false);navigate('/forum');toast('Themenbereich gelöscht.'+(result.moved ? ' Inhalte wurden verschoben.' : ''));
    } catch(error) {form.querySelector('[role=alert]').textContent=error.message;} finally {button.disabled=false;}
  });
}
function editComment(comment, postId) {
  openModal(`<h2 class="modal-title">Antwort bearbeiten.</h2><form id="edit-comment-form" class="editor-form"><label for="reply-body">Deine Antwort</label><textarea id="reply-body" name="body" required minlength="2" maxlength="5000" rows="5">${esc(comment.body)}</textarea><p class="form-error" role="alert"></p><button type="submit" class="button primary">Änderungen speichern</button></form>`);
  $('#edit-comment-form').addEventListener('submit',async event => {
    event.preventDefault(); const form = event.currentTarget, button = form.querySelector('button'); button.disabled = true;
    try {await api('comments/'+comment.id,'PATCH',Object.fromEntries(new FormData(form))); showPost(postId); toast('Antwort gespeichert.');}
    catch(error) {form.querySelector('.form-error').textContent = error.message;} finally {button.disabled = false;}
  });
}
async function showPost(id) {
  if (!/^\d+$/.test(id)) return;
  openModal('<p class="modal-subtitle">Beitrag wird geladen …</p>'); const ticket = modalRequest;
  try {
    const {post,comments} = await api('posts/'+id);
    if (ticket !== modalRequest || !$('#modal').open) return;
    $('#modal-content').innerHTML = `<span class="badge ${post.kind}">${post.kind === 'blog' ? 'BLOG' : 'FORUM'} · ${esc(categories[post.category])}</span><h2 class="modal-title">${esc(post.title)}</h2><div class="article-info">${authorLink(post.author,post.user_id,post.has_avatar,post.author_tags)} · ${date(post.created)}</div><div class="post-tags">${tagBadges(post.tags)}</div><div class="article-body">${esc(post.body)}</div>${postImages(post)}${canEdit(post) ? '<div class="post-actions"><button class="text-link" id="edit-post">Beitrag bearbeiten</button><button class="delete-button" id="delete-post">Beitrag löschen</button></div>' : ''}<section class="comments-section"><h3>${comments.length} ${comments.length === 1 ? 'Antwort' : 'Antworten'}</h3>${comments.map(c => `<article class="comment"><div class="article-info">${authorLink(c.author,c.user_id,c.has_avatar,c.author_tags)} · ${date(c.created)}</div><p class="comment-body">${esc(c.body)}</p>${canEdit(c) ? `<button class="text-link" data-edit-comment="${c.id}">Antwort bearbeiten</button>` : ''}</article>`).join('') || '<p class="modal-subtitle">Noch keine Antworten.</p>'}${canWrite() && (post.kind==='blog' || post.allow_replies) ? '<form id="comment-form" class="editor-form"><label>Deine Antwort<textarea name="body" required minlength="2" maxlength="5000" rows="3" placeholder="Deine Gedanken dazu …"></textarea></label><p class="form-error" role="alert"></p><button type="submit" class="button primary small">Antwort senden →</button></form>' : canWrite() ? '<p class="modal-subtitle">In diesem Themenbereich sind neue Antworten nicht erlaubt.</p>' : '<p class="auth-switch">Lesen ist öffentlich. <button data-action="login">Anmelden</button>, um mitzureden.</p>'}</section>`;
    $('#edit-post')?.addEventListener('click',() => compose(post));
    for (const button of document.querySelectorAll('[data-edit-comment]')) button.onclick = () => editComment(comments.find(c => c.id === Number(button.dataset.editComment)),id);
    $('#comment-form')?.addEventListener('submit',async event => {
      event.preventDefault(); const form = event.currentTarget, button = form.querySelector('button'); button.disabled = true;
      try {await api('posts/'+id+'/comments','POST',Object.fromEntries(new FormData(form))); await showPost(id); renderFeed(); toast('Deine Antwort ist veröffentlicht.');}
      catch(error) {form.querySelector('.form-error').textContent = error.message;} finally {button.disabled = false;}
    });
    $('#delete-post')?.addEventListener('click',() => {
      openModal('<h2 class="modal-title">Beitrag wirklich löschen?</h2><p class="modal-subtitle">Auch alle Antworten werden unwiderruflich gelöscht.</p><p class="form-error" role="alert"></p><div class="confirm-row"><button class="button secondary" id="cancel-delete">Abbrechen</button><button class="button primary" id="confirm-delete">Endgültig löschen</button></div>');
      $('#cancel-delete').onclick = () => showPost(id);
      $('#confirm-delete').onclick = async event => {
        event.currentTarget.disabled = true;
        try {await api('posts/'+id,'DELETE'); await loadTopics(); closeModal(false); navigate('/forum/'+post.category); toast('Beitrag gelöscht.');}
        catch(error) {$('#modal-content .form-error').textContent = error.message; $('#confirm-delete').disabled = false;}
      };
    });
  } catch(error) {if (ticket === modalRequest) $('#modal-content').innerHTML = `<h2 class="modal-title">Beitrag nicht verfügbar</h2><p class="modal-subtitle">${esc(error.message)}</p>`;}
}
async function renderProfile(username) {
  const ticket=++requestId;
  for (const node of document.querySelectorAll('[data-nav],[data-side],[data-filter],[data-category]')) node.classList.remove('active');
  $('#hero').hidden=true;$('#feed-title').textContent='Mitgliederprofil';$('#feed-kicker').textContent='DIE MENSCHEN HINTER DEN IDEEN';
  $('#feed-heading-actions').innerHTML='';$('#filter-info').innerHTML='';$('#pagination').innerHTML='';
  $('.feed-toolbar').hidden=true;$('#mobile-categories').hidden=true;$('.community-banner').hidden=true;$('#stats').hidden=true;
  $('#posts').innerHTML='<p class="empty">Profil wird geladen …</p>';
  try {
    const [{profile},result]=await Promise.all([api('users/'+encodeURIComponent(username)),api('posts?author='+encodeURIComponent(username))]);
    if (ticket!==requestId) return;
    document.title=(profile.display_name || profile.username)+' – steckerrein.de';
    $('#posts').innerHTML=`<article class="profile-card">${avatar(profile.username,profile.has_avatar,true)}<div class="profile-main"><span class="badge">${profile.admin ? 'ADMINISTRATOR' : 'MITGLIED'}</span><h2>${esc(profile.display_name || profile.username)}</h2><div class="profile-tags">${tagBadges(profile.tags)}</div><p class="profile-handle">@${esc(profile.username)} · dabei seit ${date(profile.created)}</p><p class="profile-bio">${esc(profile.bio || 'Noch keine Bio hinterlegt.')}</p>${profile.website ? `<a class="profile-website" href="${esc(profile.website)}" target="_blank" rel="noopener noreferrer nofollow ugc">${esc(profile.website)} →</a>` : ''}<p class="profile-counts">${profile.posts} ${profile.posts===1 ? 'Beitrag' : 'Beiträge'} · ${profile.replies} ${profile.replies===1 ? 'Antwort' : 'Antworten'}</p>${canWrite() && user.id===profile.id ? '<button class="button secondary small" id="edit-profile">Profil bearbeiten</button>' : ''}</div></article><h3 class="profile-posts-title">Neueste Beiträge</h3>${result.posts.length ? result.posts.map(post => `<article class="post-card"><span class="badge ${post.kind}">${post.kind==='blog' ? 'BLOG' : 'FORUM'}</span><h3><a href="/posts/${post.id}">${esc(post.title)}</a></h3><p>${esc(post.excerpt)}</p><time class="article-info">${date(post.created)}</time></article>`).join('') : '<p class="empty">Noch keine Beiträge veröffentlicht.</p>'}`;
    $('#edit-profile')?.addEventListener('click',() => editProfile(profile));
  } catch(error) {if (ticket===requestId) $('#posts').innerHTML=`<p class="empty">${esc(error.message)}</p>`;}
}
function editProfile(profile) {
  if (!canWrite() || user.id!==profile.id) return;
  openModal(`<div class="eyebrow">DEIN PLATZ IN DER COMMUNITY</div><h2 class="modal-title">Profil bearbeiten.</h2><form id="profile-form" class="editor-form"><label>Anzeigename<input name="display_name" maxlength="60" value="${esc(profile.display_name)}" placeholder="Wie sollen wir dich nennen?"></label><label for="profile-bio">Bio</label><textarea id="profile-bio" name="bio" maxlength="1000" rows="4" placeholder="Was begeistert dich? Woran arbeitest du?">${esc(profile.bio)}</textarea><label>Website<input type="url" name="website" maxlength="300" value="${esc(profile.website)}" placeholder="https://deine-website.de"></label><label>Profilbild<input type="file" name="photo" accept="image/png,image/jpeg,image/webp"></label><p class="form-note">PNG, JPEG oder WebP, höchstens 1 MB und 4 Megapixel. Das Bild wird quadratisch zugeschnitten; Metadaten werden entfernt.</p>${profile.has_avatar ? '<label class="topic-policy"><input type="checkbox" name="remove_avatar"> Profilbild entfernen</label>' : ''}<p class="form-note">Profilbild, Bio und Website sind öffentlich. Deine E-Mail-Adresse wird nicht angezeigt.</p><p class="form-error" role="alert"></p><button class="button primary" type="submit">Profil speichern</button></form>`);
  $('#profile-form').addEventListener('submit',async event => {
    event.preventDefault();const form=event.currentTarget,button=form.querySelector('[type=submit]');button.disabled=true;
    try {
      const data={display_name:form.elements.display_name.value,bio:form.elements.bio.value,website:form.elements.website.value,remove_avatar:!!form.elements.remove_avatar?.checked};
      const file=form.elements.photo.files[0];
      if (file) {
        if (file.size>1048576) throw new Error('Das Profilbild darf höchstens 1 MB groß sein.');
        data.avatar=await new Promise((resolve,reject) => {const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('Das Bild konnte nicht gelesen werden.'));reader.readAsDataURL(file);});
      }
      await api('profile','PATCH',data);user=(await api('me')).user;account();closeModal(false);await renderProfile(profile.username);toast('Profil gespeichert.');
    } catch(error) {form.querySelector('.form-error').textContent=error.message;} finally {button.disabled=false;}
  });
}
async function renderAdmin() {
  const ticket=++requestId;view='admin';category='';
  $('#hero').hidden=true;$('#feed-title').textContent='Adminbereich';$('#feed-kicker').textContent='DEINE COMMUNITY VERWALTEN';$('#feed-heading-actions').innerHTML='';$('#filter-info').innerHTML='';$('#pagination').innerHTML='';
  for (const selector of ['.feed-toolbar','#mobile-categories','.community-banner','#stats']) $(selector).hidden=true;
  for (const node of document.querySelectorAll('[data-nav],[data-side],[data-filter]')) node.classList.toggle('active',node.dataset.nav==='admin');
  document.title='Adminbereich – steckerrein.de';
  if (!canWrite() || !user.admin) {
    $('#posts').innerHTML='<div class="empty"><h3>Nur für Administratoren</h3><p>Bitte melde dich mit einem verifizierten Administratorkonto an.</p>'+(!user ? '<button class="button secondary" data-action="login">Anmelden</button>' : '')+'</div>';return;
  }
  const requested=new URLSearchParams(location.search).get('tab') || 'topics';
  const tab=['topics','post','user','members'].includes(requested) ? requested : 'topics';
  $('#posts').innerHTML='<p class="empty">Verwaltung wird geladen …</p>';
  try {
    await Promise.all([loadTags(),loadTopics()]);
    const result=tab==='members' ? await api('admin/users?'+new URLSearchParams({q:adminSearch,page:adminPage})) : null;
    if (ticket!==requestId) return;
    let body='';
    if (tab==='topics') body=`<div class="admin-heading"><div><h3>Themenbereiche</h3><p>Hierarchie, Schreibfreigabe und Inhalte verwalten.</p></div><button class="button primary small" data-action="new-topic">＋ Themenbereich</button></div><div class="admin-list">${orderedTopics().map(t => `<div class="admin-row"><div><a href="/forum/${t.slug}">${esc(topicLabel(t))}</a><small>${t.allow_posts ? 'Beiträge erlaubt' : 'Keine neuen Beiträge'} · ${t.allow_replies ? 'Antworten erlaubt' : 'Antworten gesperrt'} · ${t.children} Unterthemen</small></div><div class="admin-row-actions"><button class="text-link" data-action="edit-topic" data-topic="${t.slug}" aria-label="${esc(t.name)} bearbeiten">Bearbeiten</button><button class="delete-button" data-action="delete-topic" data-topic="${t.slug}" aria-label="${esc(t.name)} löschen">Löschen</button></div></div>`).join('')}</div>`;
    if (tab==='post' || tab==='user') body=`<div class="admin-heading"><div><h3>${tab==='post' ? 'Beitragstags' : 'Nutzertags'}</h3><p>${tab==='post' ? 'Autoren wählen diese Tags beim Schreiben ihrer Beiträge aus.' : 'Nutzertags werden unter Mitglieder zugewiesen. Sie vergeben keine Administratorrechte.'}</p></div><button class="button primary small" data-action="new-tag" data-kind="${tab}">＋ Tag anlegen</button></div><div class="admin-list">${tagCatalog.filter(t => t.kind===tab).map(t => `<div class="admin-row"><div>${tagBadges([t])}<small>${t.uses} Zuweisungen</small></div><div class="admin-row-actions"><button class="text-link" data-action="edit-tag" data-tag="${t.id}" aria-label="Tag ${esc(t.name)} bearbeiten">Bearbeiten</button><button class="delete-button" data-action="delete-tag" data-tag="${t.id}" aria-label="Tag ${esc(t.name)} löschen">Löschen</button></div></div>`).join('') || '<p class="empty">Noch keine Tags. Lege den ersten Tag an.</p>'}</div>`;
    if (tab==='members') body=`<div class="admin-heading"><div><h3>Mitglieder & Nutzertags</h3><p>Öffentliche Kennzeichnungen zuweisen, ändern oder entfernen.</p></div></div><form id="admin-user-search" class="admin-search"><label class="sr-only" for="admin-search">Mitglieder suchen</label><input id="admin-search" name="q" maxlength="80" placeholder="Nutzername oder Anzeigename" value="${esc(adminSearch)}"><button class="button secondary small">Suchen</button></form><div class="admin-list">${result.users.map(member => `<div class="admin-row"><div><a href="/users/${encodeURIComponent(member.username)}">${esc(member.display_name || member.username)} <span class="muted">@${esc(member.username)}</span></a><div class="profile-tags">${tagBadges(member.tags)}</div><small>${member.admin ? 'Administrator' : 'Mitglied'} · ${member.email_verified ? 'E-Mail bestätigt' : 'E-Mail noch nicht bestätigt'}</small></div><button class="button secondary small" data-action="user-tags" data-member="${member.id}">Nutzertags zuweisen</button></div>`).join('') || '<p class="empty">Keine Mitglieder gefunden.</p>'}</div><div class="pagination"><button class="plain" data-action="admin-previous" ${adminPage===1 ? 'disabled' : ''}>← Zurück</button><span>${adminPage} / ${Math.max(1,Math.ceil(result.total/50))}</span><button class="plain" data-action="admin-next" ${adminPage*50>=result.total ? 'disabled' : ''}>Weiter →</button></div>`;
    $('#posts').innerHTML=`<nav class="admin-tabs" aria-label="Administration">${[['topics','Themenbereiche'],['post','Beitragstags'],['user','Nutzertags'],['members','Mitglieder']].map(([key,label]) => `<a class="${key===tab ? 'active' : ''}" href="/admin?tab=${key}">${label}</a>`).join('')}</nav>${body}`;
    $('#admin-user-search')?.addEventListener('submit',event => {event.preventDefault();adminSearch=new FormData(event.currentTarget).get('q');adminPage=1;renderAdmin();});
    for (const button of document.querySelectorAll('[data-member]')) button.onclick=()=>assignUserTags(result.users.find(m => m.id===Number(button.dataset.member)));
  } catch(error) {if (ticket===requestId) $('#posts').innerHTML=`<p class="empty">${esc(error.message)}</p>`;}
}
function editTag(kind, tag=null) {
  if (!canWrite() || !user.admin) return;
  const colors={purple:'Violett',green:'Grün',blue:'Blau',orange:'Orange',red:'Rot',gray:'Grau'};
  openModal(`<div class="eyebrow">${kind==='post' ? 'BEITRAGSTAG' : 'NUTZERTAG'}</div><h2 class="modal-title">Tag ${tag ? 'bearbeiten' : 'anlegen'}.</h2><form id="tag-form" class="editor-form"><label>Name<input name="name" required maxlength="40" value="${esc(tag?.name || '')}" placeholder="${kind==='post' ? 'Zum Beispiel: Bambu Lab A1' : 'Zum Beispiel: 3D-Druck Experte'}"></label><label for="tag-color">Farbe</label><select id="tag-color" name="color">${Object.entries(colors).map(([value,label])=>`<option value="${value}" ${(tag?.color || 'purple')===value ? 'selected' : ''}>${label}</option>`).join('')}</select><p class="form-error" role="alert"></p><button class="button primary" type="submit">Tag speichern</button></form>`);
  $('#tag-form').addEventListener('submit',async event => {
    event.preventDefault();const form=event.currentTarget,button=form.querySelector('button');button.disabled=true;
    try {await api(tag ? 'admin/tags/'+tag.id : 'admin/tags',tag ? 'PATCH' : 'POST',{...Object.fromEntries(new FormData(form)),kind});closeModal(false);await renderAdmin();toast('Tag gespeichert.');}
    catch(error) {form.querySelector('.form-error').textContent=error.message;} finally {button.disabled=false;}
  });
}
function deleteTag(tag) {
  if (!tag || !canWrite() || !user.admin) return;
  openModal(`<h2 class="modal-title">Tag „${esc(tag.name)}“ löschen?</h2><p class="modal-subtitle">Der Tag und seine ${tag.uses} Zuweisungen werden entfernt. Beiträge und Nutzer bleiben erhalten.</p><p class="form-error" role="alert"></p><div class="confirm-row"><button class="button secondary" id="cancel-tag-delete">Abbrechen</button><button class="button primary" id="confirm-tag-delete">Tag endgültig löschen</button></div>`);
  $('#cancel-tag-delete').onclick=()=>closeModal(false);
  $('#confirm-tag-delete').onclick=async event => {
    event.currentTarget.disabled=true;
    try {await api('admin/tags/'+tag.id,'DELETE');closeModal(false);await renderAdmin();toast('Tag gelöscht.');}
    catch(error) {$('#modal-content .form-error').textContent=error.message;$('#confirm-tag-delete').disabled=false;}
  };
}
function assignUserTags(member) {
  if (!member || !canWrite() || !user.admin) return;
  openModal(`<div class="eyebrow">MITGLIED VERWALTEN</div><h2 class="modal-title">Tags für ${esc(member.username)}.</h2><p class="modal-subtitle">Höchstens zehn öffentliche Nutzertags. Tags ändern keine Gruppenrechte.</p><form id="user-tags-form" class="editor-form">${tagChoices('user',member.tags)}<p class="form-error" role="alert"></p><button class="button primary" type="submit">Zuweisung speichern</button></form>`);
  $('#user-tags-form').addEventListener('submit',async event => {
    event.preventDefault();const form=event.currentTarget,button=form.querySelector('button');button.disabled=true;
    try {await api('admin/users/'+member.id+'/tags','PATCH',{tag_ids:new FormData(form).getAll('tag_ids').map(Number)});closeModal(false);await renderAdmin();toast('Nutzertags aktualisiert.');}
    catch(error) {form.querySelector('.form-error').textContent=error.message;} finally {button.disabled=false;}
  });
}
function verifyEmail(token) {
  // Remove the token from the address bar immediately; it is never sent in a GET.
  history.replaceState({},'', '/');
  openModal('<h2 class="modal-title">E-Mail-Adresse bestätigen.</h2><p class="modal-subtitle">Bestätige deine Adresse, um dich anschließend anmelden zu können.</p><p class="form-error" role="alert"></p><button class="button primary" id="verify-email">E-Mail-Adresse bestätigen</button>');
  $('#verify-email').onclick = async event => {
    event.currentTarget.disabled = true;
    try {await api('verify-email','POST',{token}); openModal('<h2 class="modal-title">E-Mail-Adresse bestätigt!</h2><p class="modal-subtitle">Du kannst dich jetzt anmelden und mitmachen.</p><button class="button primary" data-action="login">Jetzt anmelden</button>');}
    catch(error) {$('#modal-content .form-error').textContent = error.message; $('#verify-email').disabled = false;}
  };
}
async function route() {
  const path = location.pathname;
  closeModal(false);
  if (path==='/admin') {returnPath=path;return renderAdmin();}
  const profileRoute=/^\/users\/([A-Za-z0-9_-]+)$/.exec(path);
  if (profileRoute) {returnPath=path;return renderProfile(profileRoute[1]);}
  for (const selector of ['.feed-toolbar','#mobile-categories','.community-banner','#stats']) $(selector).hidden=false;
  const nextView = path.startsWith('/forum') ? 'forum' : path === '/blog' ? 'blog' : 'home';
  if (path.startsWith('/posts/')) {await renderFeed(); return showPost(path.split('/')[2]);}
  returnPath = path;
  if (view !== nextView) {page=1;search='';$('#search').value='';}
  view = nextView; category = path.startsWith('/forum/') ? path.split('/')[2] : '';
  await renderFeed();
  if (view !== 'home') $('#workspace').scrollIntoView({block:'start'});
}
$('#year').textContent = new Date().getFullYear();
const oldButton = $('.feed-heading > button');
oldButton.outerHTML = '<div id="feed-heading-actions" class="heading-actions"></div>';
account();
$('#search-form').addEventListener('submit',event => {event.preventDefault();search=$('#search').value.trim();page=1;renderFeed();});
$('#search').addEventListener('input',event => {if (!event.target.value && search) {search='';page=1;renderFeed();}});
$('.close-modal').onclick = () => closeModal();
$('#modal').addEventListener('cancel',event => {event.preventDefault();closeModal();});
document.addEventListener('click',async event => {
  const anchor = event.target.closest('a[href]');
  if (anchor && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey && event.button === 0 && !anchor.target) {
    const url = new URL(anchor.href,location.href);
    if (url.origin === location.origin && /^\/(?:forum(?:\/[a-z0-9-]+)?|blog|admin|posts\/\d+|users\/[A-Za-z0-9_-]+)?$/.test(url.pathname) && !url.hash) {event.preventDefault();navigate(url.pathname+url.search);return;}
  }
  const element = event.target.closest('[data-action],[data-filter]'); if (!element) return;
  if (element.dataset.filter) {navigate(element.dataset.filter === 'home' ? '/' : '/'+element.dataset.filter);return;}
  const action = element.dataset.action;
  if (['login','register','resend'].includes(action)) auth(action);
  if (action === 'compose') compose();
  if (action === 'new-tag') editTag(element.dataset.kind);
  if (action === 'edit-tag') {const tag=tagCatalog.find(t=>t.id===Number(element.dataset.tag));if(tag) editTag(tag.kind,tag);}
  if (action === 'delete-tag') deleteTag(tagCatalog.find(t=>t.id===Number(element.dataset.tag)));
  if (action === 'admin-previous' && adminPage>1) {adminPage--;renderAdmin();}
  if (action === 'admin-next') {adminPage++;renderAdmin();}
  if (action === 'new-topic') newTopic();
  if (action === 'edit-topic') {const topic=topics.find(t => t.slug === (element.dataset.topic || category));if (topic) newTopic(topic);}
  if (action === 'delete-topic') deleteTopic(topics.find(t => t.slug === (element.dataset.topic || category)));
  if (action === 'retry') {try {await loadTopics();renderFeed();} catch(error) {toast(error.message);}}
  if (action === 'previous' && page>1) {page--;renderFeed();}
  if (action === 'next') {page++;renderFeed();}
  if (action === 'logout') {
    try {await api('logout','POST');user=null;account();closeModal(false);await route();toast('Du bist abgemeldet.');}
    catch(error) {toast(error.message);}
  }
});
window.addEventListener('popstate',route);
(async () => {
  const results = await Promise.allSettled([api('me'),loadTopics(),loadTags()]);
  if (results[0].status === 'fulfilled') user=results[0].value.user; else toast(results[0].reason.message);
  if (results[1].status === 'rejected') toast(results[1].reason.message);
  account();await route();
  if (location.hash.startsWith('#verify/')) verifyEmail(location.hash.slice(8));
  // Compatibility with links from the first community version.
  else if (location.hash === '#forum' || location.hash === '#blog') navigate('/'+location.hash.slice(1));
  else if (/^#post\/\d+$/.test(location.hash)) navigate('/posts/'+location.hash.split('/')[1]);
})();
