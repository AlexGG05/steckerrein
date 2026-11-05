'use strict';
const $ = (selector) => document.querySelector(selector);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const categories = {'it':'IT & Homelab','3d-druck':'3D-Druck','projekte':'Projekte & Builds','allgemein':'Allgemein'};
let user = null, view = 'home', category = '', search = '', page = 1, requestId = 0, modalRequest = 0;
const date = value => new Date(value * 1000).toLocaleDateString('de-DE', {day:'numeric',month:'short',year:'numeric'});
async function api(path, method = 'GET', data) {
  const options = {method, headers: {}};
  if (method !== 'GET') {
    options.headers = {'Content-Type':'application/json', 'X-Requested-With':'Steckerrein'};
    options.body = JSON.stringify(data || {});
  }
  let response;
  try { response = await fetch('/api/' + path, options); }
  catch { throw new Error('Verbindung fehlgeschlagen. Bitte versuche es erneut.'); }
  let result;
  try { result = await response.json(); } catch { throw new Error('Der Server ist gerade nicht erreichbar.'); }
  if (!response.ok) throw new Error(result.error || 'Die Anfrage ist fehlgeschlagen.');
  return result;
}
function toast(message) {
  $('#toast').textContent = message; $('#toast').style.display = 'block';
  clearTimeout(toast.timer); toast.timer = setTimeout(() => $('#toast').style.display = 'none', 4500);
}
function account() {
  $('#account').innerHTML = user
    ? `<span class="avatar" aria-hidden="true">${esc(user.username[0].toUpperCase())}</span><span class="account-name">${esc(user.username)}</span><button class="plain" data-action="logout">Abmelden</button>`
    : '<button class="plain" data-action="login">Anmelden</button><button class="button secondary small" data-action="register">Mitmachen →</button>';
}
function openModal(html) {
  modalRequest++;
  $('#modal-content').innerHTML = html;
  if (!$('#modal').open) $('#modal').showModal();
  $('#modal').scrollTop = 0;
}
function closeModal() { modalRequest++; $('#modal').close(); }
function navigate(next) {
  location.hash = next === 'home' ? '' : next;
  // The hashchange event does not fire when the current hash is selected.
  if ((location.hash.slice(1) || 'home') === view) renderFeed();
}
async function renderFeed() {
  const id = ++requestId;
  for (const node of document.querySelectorAll('[data-nav],[data-side],[data-filter]')) {
    node.classList.toggle('active', (node.dataset.nav || node.dataset.side || node.dataset.filter) === view);
  }
  for (const node of document.querySelectorAll('[data-category]')) node.classList.toggle('active', node.dataset.category === category);
  $('#hero').hidden = view !== 'home';
  $('#feed-title').innerHTML = (view === 'forum' ? 'Im Gespräch' : view === 'blog' ? 'Gedanken & Anleitungen' : 'Frische Impulse') + '<span>.</span>';
  $('#feed-kicker').textContent = view === 'forum' ? 'FRAGEN. HELFEN. WEITERKOMMEN.' : view === 'blog' ? 'NEUES AUS DER WERKSTATT' : 'WISSEN WÄCHST, WENN MAN ES TEILT';
  $('#filter-info').innerHTML = category ? `<span class="filter-pill">${esc(categories[category])}<button data-action="clear-category" aria-label="Kategoriefilter entfernen">✕</button></span>` : '';
  $('#posts').innerHTML = '<div class="empty">Beiträge werden geladen …</div>';
  const params = new URLSearchParams({page});
  if (view !== 'home') params.set('kind', view);
  if (category) params.set('category', category);
  if (search) params.set('q', search);
  try {
    const result = await api('posts?' + params);
    if (id !== requestId) return;
    $('#posts').innerHTML = result.posts.length ? result.posts.map(post => `<article class="post-card"><div class="post-meta"><span class="badge ${post.kind}">${post.kind === 'blog' ? 'AUS DEM BLOG' : 'DISKUSSION'}</span><span class="category-text">${esc(categories[post.category])}</span></div><h3><a href="#post/${post.id}">${esc(post.title)}</a></h3><p>${esc(post.excerpt)}</p><div class="post-bottom"><span class="avatar" aria-hidden="true">${esc(post.author[0].toUpperCase())}</span><span>${esc(post.author)}</span><span>·</span><time datetime="${new Date(post.created*1000).toISOString()}">${date(post.created)}</time><span class="reply-count">▤ &nbsp; ${post.comments} ${post.comments === 1 ? 'Antwort' : 'Antworten'}</span></div><span class="card-arrow" aria-hidden="true">→</span></article>`).join('')
      : `<div class="empty"><h3>${search ? 'Noch kein Treffer.' : 'Hier ist Platz für deinen ersten Beitrag.'}</h3><p>${search ? 'Versuche einen anderen Suchbegriff oder entferne den Filter.' : 'Teile eine Frage, eine Idee oder dein aktuelles Projekt mit der Community.'}</p><button class="button secondary small" data-action="${search ? 'clear-search' : 'compose'}">${search ? 'Suche zurücksetzen' : 'Thema eröffnen →'}</button></div>`;
    $('#pagination').innerHTML = result.total > 12 ? `<button class="plain" data-action="previous" ${page === 1 ? 'disabled' : ''}>← Zurück</button><span>${page} / ${Math.ceil(result.total/12)}</span><button class="plain" data-action="next" ${page*12 >= result.total ? 'disabled' : ''}>Weiter →</button>` : '';
    const s = result.stats;
    $('#stats').innerHTML = `<span><strong>${s.members}</strong> ${s.members === 1 ? 'Mitglied' : 'Mitglieder'}</span><span><strong>${s.topics}</strong> Diskussionen</span><span><strong>${s.articles}</strong> Blogartikel</span><span><span class="status-dot"></span> &nbsp; Raum für deine Ideen</span>`;
  } catch (error) {
    if (id === requestId) $('#posts').innerHTML = `<div class="empty"><p>${esc(error.message)}</p><button class="button secondary small" data-action="retry">Erneut versuchen</button></div>`;
  }
}
function auth(mode = 'login') {
  const register = mode === 'register';
  openModal(`<div class="eyebrow">DEIN PLATZ IN DER COMMUNITY</div><h2 class="modal-title">${register ? 'Schön, dass du mitmachst.' : 'Willkommen zurück.'}</h2><p class="modal-subtitle">${register ? 'Ein Konto. Viele Ideen. Lass uns gemeinsam etwas bauen.' : 'Melde dich an und bring deine Ideen ins Gespräch.'}</p><form class="editor-form" id="auth-form"><label>Nutzername<input name="username" required minlength="3" maxlength="24" pattern="[A-Za-z0-9_-]+" autocomplete="username" placeholder="Dein Nutzername"></label><label>Passwort<input name="password" type="password" required minlength="10" maxlength="128" autocomplete="${register ? 'new-password' : 'current-password'}" placeholder="Mindestens 10 Zeichen"></label>${register ? '<p class="form-note">Dein Nutzername ist öffentlich. Wir benötigen keine E-Mail-Adresse. Bitte bewahre dein Passwort sicher auf; eine automatische Wiederherstellung gibt es derzeit nicht. Hinweise findest du im <a href="impressum.html" target="_blank" rel="noopener">Impressum</a> und <a href="datenschutz.html" target="_blank" rel="noopener">Datenschutz</a>.</p>' : ''}<p class="form-error" role="alert"></p><button class="button primary" type="submit">${register ? 'Konto erstellen' : 'Anmelden'} →</button></form><p class="auth-switch">${register ? 'Schon dabei?' : 'Noch kein Konto?'} <button data-action="${register ? 'login' : 'register'}">${register ? 'Anmelden' : 'Jetzt mitmachen'}</button></p>`);
  $('#auth-form').addEventListener('submit', async event => {
    event.preventDefault(); const form = event.currentTarget; const button = form.querySelector('[type=submit]'); button.disabled = true;
    try {
      const result = await api(register ? 'register' : 'login','POST',Object.fromEntries(new FormData(form)));
      user = result.user; account(); closeModal(); toast(register ? 'Willkommen in der Community!' : 'Du bist angemeldet.');
      if (location.hash.startsWith('#post/')) showPost(location.hash.split('/')[1]);
      else renderFeed();
    } catch (error) { form.querySelector('.form-error').textContent = error.message; }
    finally { button.disabled = false; }
  });
}
function compose() {
  if (!user) return auth('register');
  openModal(`<div class="eyebrow">WAS BESCHÄFTIGT DICH?</div><h2 class="modal-title">Bring etwas ins Rollen.</h2><p class="modal-subtitle">Eine gute Frage ist oft der beste Anfang.</p><form id="post-form" class="editor-form">${user.admin ? '<label>Beitragsart<select name="kind"><option value="forum">Diskussion im Forum</option><option value="blog">Blogartikel veröffentlichen</option></select></label>' : '<input type="hidden" name="kind" value="forum">'}<label>Themenwelt<select name="category">${Object.entries(categories).map(([key,label]) => `<option value="${key}" ${category === key ? 'selected' : ''}>${label}</option>`).join('')}</select></label><label>Titel<input name="title" required minlength="5" maxlength="140" placeholder="Worum geht es? Sei gern konkret."></label><label>Dein Beitrag<textarea name="body" required minlength="20" maxlength="15000" rows="8" placeholder="Erzähl uns von deiner Idee, deinem Projekt oder deiner Frage …"></textarea></label><p class="form-note">Bleib freundlich. Teile keine Passwörter, persönlichen Daten Dritter oder fremde Inhalte ohne Erlaubnis. Beiträge sind öffentlich sichtbar.</p><p class="form-error" role="alert"></p><button class="button primary" type="submit">Beitrag veröffentlichen →</button></form>`);
  $('#post-form').addEventListener('submit', async event => {
    event.preventDefault(); const form = event.currentTarget; const button = form.querySelector('[type=submit]'); button.disabled = true;
    try {
      const result = await api('posts','POST',Object.fromEntries(new FormData(form)));
      closeModal(); toast('Dein Beitrag ist veröffentlicht.'); location.hash = 'post/' + result.id;
    } catch(error) { form.querySelector('.form-error').textContent = error.message; }
    finally {button.disabled = false;}
  });
}
async function showPost(id) {
  if (!/^\d+$/.test(id)) return;
  openModal('<p class="modal-subtitle">Beitrag wird geladen …</p>');
  const ticket = modalRequest;
  try {
    const {post, comments} = await api('posts/' + id);
    if (ticket !== modalRequest || !$('#modal').open) return;
    $('#modal-content').innerHTML = `<span class="badge ${post.kind}">${post.kind === 'blog' ? 'BLOG' : 'FORUM'} · ${esc(categories[post.category])}</span><h2 class="modal-title">${esc(post.title)}</h2><div class="article-info">${esc(post.author)} · ${date(post.created)}</div><div class="article-body">${esc(post.body)}</div>${user && (user.id === post.user_id || user.admin) ? '<button class="delete-button" id="delete-post">Beitrag löschen</button>' : ''}<section class="comments-section"><h3>${comments.length} ${comments.length === 1 ? 'Antwort' : 'Antworten'}</h3>${comments.length ? comments.map(comment => `<article class="comment"><div class="article-info"><strong>${esc(comment.author)}</strong> · ${date(comment.created)}</div><p class="comment-body">${esc(comment.body)}</p></article>`).join('') : '<p class="modal-subtitle">Noch keine Antworten. Mach den Anfang!</p>'}${user ? '<form id="comment-form" class="editor-form"><label>Deine Antwort<textarea name="body" required minlength="2" maxlength="5000" rows="3" placeholder="Deine Gedanken dazu …"></textarea></label><p class="form-error" role="alert"></p><button type="submit" class="button primary small">Antwort senden →</button></form>' : '<p class="auth-switch"><button data-action="login">Melde dich an</button>, um mitzureden.</p>'}</section>`;
    $('#comment-form')?.addEventListener('submit',async event => {
      event.preventDefault(); const form = event.currentTarget; const button = form.querySelector('button'); button.disabled = true;
      try { await api('posts/' + id + '/comments','POST',Object.fromEntries(new FormData(form))); await showPost(id); renderFeed(); toast('Deine Antwort ist veröffentlicht.'); }
      catch(error) { form.querySelector('.form-error').textContent = error.message; }
      finally { button.disabled = false; }
    });
    $('#delete-post')?.addEventListener('click',() => {
      openModal('<h2 class="modal-title">Beitrag wirklich löschen?</h2><p class="modal-subtitle">Dabei werden auch alle Antworten zu diesem Beitrag gelöscht. Das kann nicht rückgängig gemacht werden.</p><p class="form-error" role="alert"></p><div class="confirm-row"><button class="button secondary" id="cancel-delete">Abbrechen</button><button class="button primary" id="confirm-delete">Endgültig löschen</button></div>');
      $('#cancel-delete').onclick = () => showPost(id);
      $('#confirm-delete').onclick = async event => {
        event.currentTarget.disabled = true;
        try { await api('posts/'+id,'DELETE'); closeModal(); location.hash = view === 'home' ? '' : view; renderFeed(); toast('Beitrag gelöscht.'); }
        catch(error) { $('#modal-content .form-error').textContent = error.message; $('#confirm-delete').disabled = false; }
      };
    });
  } catch(error) { if (ticket === modalRequest) $('#modal-content').innerHTML = `<h2 class="modal-title">Beitrag nicht verfügbar</h2><p class="modal-subtitle">${esc(error.message)}</p>`; }
}
async function route() {
  const hash = location.hash.slice(1);
  if (hash.startsWith('post/')) { await showPost(hash.split('/')[1]); return; }
  const next = ['forum','blog'].includes(hash) ? hash : 'home';
  if (next !== view) {page = 1; category = '';}
  view = next;
  closeModal(); await renderFeed();
}
$('#categories').innerHTML = Object.entries(categories).map(([key,label]) => `<button class="category-link" data-category="${key}"><i></i>${label}</button>`).join('');
$('#mobile-categories').innerHTML = $('#categories').innerHTML;
$('#year').textContent = new Date().getFullYear();
$('#search-form').addEventListener('submit',event => {event.preventDefault(); search = $('#search').value.trim(); page = 1; renderFeed();});
$('#search').addEventListener('input',event => {if (!event.target.value && search) {search = '';page=1;renderFeed();}});
$('.close-modal').onclick = closeModal;
$('#modal').addEventListener('cancel',() => {modalRequest++;});
$('#modal').addEventListener('click',event => {if (event.target === $('#modal')) {const rect = $('#modal').getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) closeModal();}});
document.addEventListener('click',async event => {
  const element = event.target.closest('[data-action],[data-filter],[data-category]');
  if (!element) return;
  if (element.dataset.filter) {navigate(element.dataset.filter);return;}
  if (element.dataset.category) {category = element.dataset.category;page = 1;renderFeed();return;}
  const action = element.dataset.action;
  if (action === 'login' || action === 'register') auth(action);
  if (action === 'compose') compose();
  if (action === 'clear-category') {category='';page=1;renderFeed();}
  if (action === 'clear-search') {search='';$('#search').value='';page=1;renderFeed();}
  if (action === 'retry') renderFeed();
  if (action === 'previous' && page > 1) {page--;renderFeed();}
  if (action === 'next') {page++;renderFeed();}
  if (action === 'logout') {
    try {await api('logout','POST');user=null;account();toast('Du bist abgemeldet.'); if (location.hash.startsWith('#post/')) showPost(location.hash.split('/')[1]);else renderFeed();}
    catch(error) {toast(error.message);}
  }
});
window.addEventListener('hashchange',route);
(async () => {try {user = (await api('me')).user;}catch(error) {toast(error.message);}account();await renderFeed();if (location.hash) route();})();
