'use strict';
const $ = selector => document.querySelector(selector);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let topics = [], categories = {}, user = null, view = 'home', category = '', search = '', page = 1, requestId = 0, modalRequest = 0;
let returnPath = '/forum';
const date = value => new Date(value * 1000).toLocaleDateString('de-DE', {day:'numeric',month:'short',year:'numeric'});
const canWrite = () => !!(user && user.email_verified);
const canEdit = item => canWrite() && (user.admin || user.id === item.user_id);
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
  $('#account').innerHTML = user ? `<span class="avatar" aria-hidden="true">${esc(user.username[0].toUpperCase())}</span><span class="account-name">${esc(user.username)}${user.admin ? '<small class="role-label">Administrator</small>' : ''}</span><button class="plain" data-action="logout">Abmelden</button>` : '<button class="plain" data-action="login">Anmelden</button><button class="button secondary small" data-action="register">Mitmachen →</button>';
  for (const button of document.querySelectorAll('[data-action="compose"]')) button.hidden = !canWrite();
}
function openModal(html) {
  modalRequest++; $('#modal-content').innerHTML = html;
  if (!$('#modal').open) $('#modal').showModal();
  $('#modal').scrollTop = 0;
}
function closeModal(changePath = true) {
  modalRequest++; $('#modal').close();
  if (changePath && location.pathname.startsWith('/posts/')) navigate(returnPath);
}
function navigate(path) {history.pushState({},'',path); route();}
async function loadTopics() {
  topics = (await api('topics')).topics;
  categories = Object.fromEntries(topics.map(t => [t.slug,t.name]));
  const html = topics.map(t => `<a href="/forum/${t.slug}" class="category-link" data-category="${t.slug}"><i></i>${esc(t.name)}</a>`).join('');
  $('#categories').innerHTML = html; $('#mobile-categories').innerHTML = html;
}
function controls() {
  const area = $('#feed-heading-actions');
  if (area) area.innerHTML = `${user?.admin && view === 'forum' ? '<button class="button secondary small" data-action="new-topic">＋ Themenbereich</button>' : ''}${canWrite() && (view !== 'blog' || user.admin) ? '<button class="button primary small" data-action="compose">＋ '+(view === 'blog' ? 'Blogartikel' : 'Neuer Beitrag')+'</button>' : ''}`;
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
  $('#filter-info').innerHTML = category ? `<a class="filter-pill" href="/forum">← Alle Themenbereiche</a>` : '';
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
      $('#posts').innerHTML = `<p class="forum-intro">Wähle einen Themenbereich. Angemeldete, verifizierte Mitglieder können darin Beiträge verfassen. Themenbereiche werden von Administratoren angelegt.</p><div class="board-grid">${topics.map(t => `<article class="board-card"><span class="board-icon" aria-hidden="true">▤</span><h3><a href="/forum/${t.slug}">${esc(t.name)}</a></h3><p>${esc(t.description)}</p><span>${t.posts} ${t.posts === 1 ? 'Beitrag' : 'Beiträge'} <b aria-hidden="true">→</b></span></article>`).join('')}</div>`;
    } else {
      $('#posts').innerHTML = result.posts.length ? result.posts.map(post => `<article class="post-card"><div class="post-meta"><span class="badge ${post.kind}">${post.kind === 'blog' ? 'AUS DEM BLOG' : 'BEITRAG'}</span><span class="category-text">${esc(categories[post.category])}</span></div><h3><a href="/posts/${post.id}">${esc(post.title)}</a></h3><p>${esc(post.excerpt)}</p><div class="post-bottom"><span class="avatar" aria-hidden="true">${esc(post.author[0].toUpperCase())}</span><span>${esc(post.author)}</span><span>·</span><time datetime="${new Date(post.created*1000).toISOString()}">${date(post.created)}</time><span class="reply-count">▤ &nbsp; ${post.comments} ${post.comments === 1 ? 'Antwort' : 'Antworten'}</span></div><span class="card-arrow" aria-hidden="true">→</span></article>`).join('') : `<div class="empty"><h3>${search ? 'Noch kein Treffer.' : 'Noch keine Beiträge.'}</h3><p>${search ? 'Versuche einen anderen Suchbegriff.' : canWrite() ? 'Erstelle den ersten Beitrag in diesem Themenbereich.' : 'Melde dich mit einer bestätigten E-Mail-Adresse an, um mitzumachen.'}</p>${canWrite() ? '<button class="button secondary small" data-action="compose">Beitrag erstellen →</button>' : '<button class="button secondary small" data-action="login">Anmelden</button>'}</div>`;
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
      user = result.user; account(); closeModal(false); toast('Du bist angemeldet.'); await renderFeed();
      if (location.pathname.startsWith('/posts/')) showPost(location.pathname.split('/')[2]);
    } catch(error) {
      if (error.code === 'EMAIL_UNVERIFIED') {auth('resend',data.identifier); $('#auth-form .form-error').textContent = error.message;}
      else form.querySelector('.form-error').textContent = error.message;
    } finally {button.disabled = false;}
  });
}
function compose(post = null) {
  if (!canWrite()) return auth('login');
  const kind = post?.kind || (view === 'blog' && user.admin ? 'blog' : 'forum');
  openModal(`<div class="eyebrow">WAS BESCHÄFTIGT DICH?</div><h2 class="modal-title">${post ? 'Beitrag bearbeiten.' : kind === 'blog' ? 'Ein neuer Blogartikel.' : 'Dein Beitrag zur Community.'}</h2><form id="post-form" class="editor-form"><input type="hidden" name="kind" value="${kind}"><label>Themenbereich<select name="category" required>${topics.map(t => `<option value="${t.slug}" ${(post?.category || category) === t.slug ? 'selected' : ''}>${esc(t.name)}</option>`).join('')}</select></label><label>Titel<input name="title" required minlength="5" maxlength="140" value="${esc(post?.title || '')}" placeholder="Worum geht es?"></label><label for="post-body">Dein Beitrag</label><textarea id="post-body" name="body" required minlength="20" maxlength="15000" rows="8">${esc(post?.body || '')}</textarea><p class="form-note">Beiträge sind öffentlich. Bleib freundlich und teile keine Passwörter oder persönlichen Daten Dritter.</p><p class="form-error" role="alert"></p><button class="button primary" type="submit">${post ? 'Änderungen speichern' : 'Beitrag veröffentlichen'} →</button></form>`);
  $('#post-form').addEventListener('submit',async event => {
    event.preventDefault(); const form = event.currentTarget, button = form.querySelector('button'); button.disabled = true;
    try {
      const result = await api(post ? 'posts/'+post.id : 'posts',post ? 'PATCH' : 'POST',Object.fromEntries(new FormData(form)));
      const id = post ? post.id : result.id;
      await loadTopics(); closeModal(false); toast(post ? 'Änderungen gespeichert.' : 'Dein Beitrag ist veröffentlicht.');
      if (location.pathname === '/posts/'+id) await showPost(String(id)); else navigate('/posts/'+id);
    } catch(error) {form.querySelector('.form-error').textContent = error.message;} finally {button.disabled = false;}
  });
}
function newTopic() {
  if (!canWrite() || !user.admin) return;
  openModal('<div class="eyebrow">ADMINISTRATION</div><h2 class="modal-title">Themenbereich erstellen.</h2><p class="modal-subtitle">Mitglieder können in diesem Bereich eigene Beiträge veröffentlichen.</p><form id="topic-form" class="editor-form"><label>Name<input name="name" required minlength="3" maxlength="80" placeholder="Zum Beispiel: Heimautomatisierung"></label><label>Beschreibung<textarea name="description" required minlength="10" maxlength="300" rows="3"></textarea></label><p class="form-error" role="alert"></p><button type="submit" class="button primary">Themenbereich erstellen</button></form>');
  $('#topic-form').addEventListener('submit',async event => {
    event.preventDefault(); const form = event.currentTarget, button = form.querySelector('button'); button.disabled = true;
    try {const result = await api('topics','POST',Object.fromEntries(new FormData(form))); await loadTopics(); closeModal(false); navigate('/forum/'+result.slug); toast('Themenbereich erstellt.');}
    catch(error) {form.querySelector('.form-error').textContent = error.message;} finally {button.disabled = false;}
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
    $('#modal-content').innerHTML = `<span class="badge ${post.kind}">${post.kind === 'blog' ? 'BLOG' : 'FORUM'} · ${esc(categories[post.category])}</span><h2 class="modal-title">${esc(post.title)}</h2><div class="article-info">${esc(post.author)} · ${date(post.created)}</div><div class="article-body">${esc(post.body)}</div>${canEdit(post) ? '<div class="post-actions"><button class="text-link" id="edit-post">Beitrag bearbeiten</button><button class="delete-button" id="delete-post">Beitrag löschen</button></div>' : ''}<section class="comments-section"><h3>${comments.length} ${comments.length === 1 ? 'Antwort' : 'Antworten'}</h3>${comments.map(c => `<article class="comment"><div class="article-info"><strong>${esc(c.author)}</strong> · ${date(c.created)}</div><p class="comment-body">${esc(c.body)}</p>${canEdit(c) ? `<button class="text-link" data-edit-comment="${c.id}">Antwort bearbeiten</button>` : ''}</article>`).join('') || '<p class="modal-subtitle">Noch keine Antworten.</p>'}${canWrite() ? '<form id="comment-form" class="editor-form"><label>Deine Antwort<textarea name="body" required minlength="2" maxlength="5000" rows="3" placeholder="Deine Gedanken dazu …"></textarea></label><p class="form-error" role="alert"></p><button type="submit" class="button primary small">Antwort senden →</button></form>' : '<p class="auth-switch">Lesen ist öffentlich. <button data-action="login">Anmelden</button>, um mitzureden.</p>'}</section>`;
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
    if (url.origin === location.origin && /^\/(?:forum(?:\/[a-z0-9-]+)?|blog|posts\/\d+)?$/.test(url.pathname) && !url.hash) {event.preventDefault();navigate(url.pathname);return;}
  }
  const element = event.target.closest('[data-action],[data-filter]'); if (!element) return;
  if (element.dataset.filter) {navigate(element.dataset.filter === 'home' ? '/' : '/'+element.dataset.filter);return;}
  const action = element.dataset.action;
  if (['login','register','resend'].includes(action)) auth(action);
  if (action === 'compose') compose();
  if (action === 'new-topic') newTopic();
  if (action === 'retry') {try {await loadTopics();renderFeed();} catch(error) {toast(error.message);}}
  if (action === 'previous' && page>1) {page--;renderFeed();}
  if (action === 'next') {page++;renderFeed();}
  if (action === 'logout') {
    try {await api('logout','POST');user=null;account();closeModal(false);await renderFeed();if (location.pathname.startsWith('/posts/')) showPost(location.pathname.split('/')[2]);toast('Du bist abgemeldet.');}
    catch(error) {toast(error.message);}
  }
});
window.addEventListener('popstate',route);
(async () => {
  const results = await Promise.allSettled([api('me'),loadTopics()]);
  if (results[0].status === 'fulfilled') user=results[0].value.user; else toast(results[0].reason.message);
  if (results[1].status === 'rejected') toast(results[1].reason.message);
  account();await route();
  if (location.hash.startsWith('#verify/')) verifyEmail(location.hash.slice(8));
  // Compatibility with links from the first community version.
  else if (location.hash === '#forum' || location.hash === '#blog') navigate('/'+location.hash.slice(1));
  else if (/^#post\/\d+$/.test(location.hash)) navigate('/posts/'+location.hash.split('/')[1]);
})();
