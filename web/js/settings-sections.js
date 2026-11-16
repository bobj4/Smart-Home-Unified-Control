/**
 * Settings pages with several sections (Admin above all): each section's
 * heading folds it shut or open, remembered for the person, and a row of
 * links at the top jumps to a section (opening it).
 */

function sectionKey(pageId, sub) {
  const heading = sub.querySelector(':scope > h3');
  return `${pageId}/${sub.dataset.testid || heading.textContent}`.slice(0, 100);
}

function saveCollapsed(app, shut) {
  app.account.collapsed_sections = [...shut];
  app.api.setCollapsed([...shut]).catch((error) => app.handleError(error));
}

/** Make the panel's sections foldable; adds the jump links. */
function makeCollapsible(app, pageId, panel) {
  const subs = [...panel.children].filter((c) => c.classList.contains('subpanel') && c.querySelector(':scope > h3'));
  if (subs.length < 2) return;
  const shut = new Set(app.account.collapsed_sections || []);
  const setOpen = (sub, heading, open) => {
    sub.classList.toggle('collapsed', !open);
    heading.setAttribute('aria-expanded', String(open));
  };
  const links = subs.map((sub) => {
    const heading = sub.querySelector(':scope > h3');
    const key = sectionKey(pageId, sub);
    heading.classList.add('section-toggle');
    heading.setAttribute('role', 'button');
    heading.setAttribute('tabindex', '0');
    sub.dataset.section = key;
    setOpen(sub, heading, !shut.has(key));
    const toggle = () => {
      const open = sub.classList.contains('collapsed');
      setOpen(sub, heading, open);
      if (open) shut.delete(key); else shut.add(key);
      saveCollapsed(app, shut);
    };
    heading.addEventListener('click', toggle);
    heading.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
    });
    return el('button', {
      type: 'button', className: 'chip', testid: 'section-jump-link', text: heading.textContent,
      onclick: () => {
        if (sub.classList.contains('collapsed')) toggle();
        sub.scrollIntoView({ behavior: 'smooth', block: 'start' });
      },
    });
  });
  const all = el('button', {
    type: 'button', className: 'chip', testid: 'section-fold-all', text: 'Fold all',
    onclick: () => {
      const folding = subs.some((s) => !s.classList.contains('collapsed'));
      subs.forEach((sub) => {
        setOpen(sub, sub.querySelector(':scope > h3'), !folding);
        if (folding) shut.add(sectionKey(pageId, sub)); else shut.delete(sectionKey(pageId, sub));
      });
      saveCollapsed(app, shut);
    },
  });
  const intro = panel.querySelector(':scope > p.muted') || panel.querySelector(':scope > h2');
  intro.after(el('nav', { className: 'section-jump', testid: 'section-jump', 'aria-label': 'Sections' }, [...links, all]));
}

/** Turn the group's own sections into smaller parts of it (they keep
 * their headings, shown smaller, and fold with the group). */
function nestSections(group) {
  [...group.children].forEach((child) => child.classList.replace('subpanel', 'subsection'));
  return group;
}

/** One foldable section made of several smaller ones. */
function groupSections(title, testid, parts) {
  return nestSections(el('div', { className: 'subpanel', testid }, [el('h3', { text: title }), ...parts.filter(Boolean)]));
}

window.makeCollapsible = makeCollapsible;
window.nestSections = nestSections;
window.groupSections = groupSections;
