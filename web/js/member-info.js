/**
 * Names and logins: an admin's Edit button on each member (Settings >
 * Members), the admin setting that lets people change their own, and the
 * "Your details" form in My account when it is allowed.
 */

/** The Edit button on a member row: name and login, in place. */
function memberInfoButton(view, member) {
  return el('button', {
    type: 'button', className: 'secondary', testid: 'member-edit', text: 'Edit',
    onclick: (event) => {
      const row = event.currentTarget.closest('.member-row');
      const name = el('input', { type: 'text', testid: 'member-edit-name', maxlength: '100', value: member.name || '', 'aria-label': 'Name' });
      const email = el('input', { type: 'text', testid: 'member-edit-email', maxlength: '255', required: true, value: member.email, 'aria-label': 'Email or username' });
      const form = el('form', { className: 'subpanel', testid: 'member-edit-form' }, [
        el('div', { className: 'grid-fields' }, [field('Name', name), field('Email or username (their login)', email)]),
        el('div', { className: 'row' }, [
          el('button', { type: 'submit', testid: 'member-edit-save', text: 'Save' }),
          el('button', { type: 'button', className: 'secondary', text: 'Cancel', onclick: () => view.loadMembers() }),
        ]),
      ]);
      form.addEventListener('submit', (e) => {
        e.preventDefault();
        view.app.run(async () => {
          await view.app.api.editMemberInfo(view.app.home.id, member.user_id, { name: name.value.trim() || null, email: email.value.trim() });
          await view.loadMembers();
          view.app.status.success('Details saved.');
        });
      });
      row.replaceChildren(form);
      name.focus();
    },
  });
}

/** Settings > Admin: may people change their own name and email? */
class SelfEditPanel {
  constructor(app) {
    this.app = app;
  }

  async render(container) {
    const current = await this.app.api.getSelfEdit();
    const box = el('input', { type: 'checkbox', testid: 'self-edit', checked: current.allowed });
    box.addEventListener('change', () => this.app.run(async () => {
      const saved = await this.app.api.setSelfEdit(box.checked);
      this.app.status.success(saved.allowed ? 'People can now change their own name and email.' : 'Only admins can change names and emails now.');
    }));
    container.append(el('div', { className: 'subpanel', testid: 'self-edit-settings' }, [
      el('h3', { text: 'Your details' }),
      el('label', { className: 'check' }, [box, ' Let people change their own name and email (My account). Changing an email needs their password.']),
    ]));
  }
}

/** My account > Your details (only when an admin allows it). */
function ownInfoBox(app) {
  const account = app.account;
  if (!account.can_edit_info) return null;
  const name = el('input', { type: 'text', testid: 'own-name', maxlength: '100', value: account.name || '', 'aria-label': 'Name' });
  const email = el('input', { type: 'text', testid: 'own-email', maxlength: '255', required: true, value: account.email, 'aria-label': 'Email or username' });
  const password = el('input', { type: 'password', testid: 'own-password', autocomplete: 'current-password', 'aria-label': 'Current password' });
  const passwordField = field('Current password (to change your login)', password);
  const check = () => { passwordField.hidden = email.value.trim().toLowerCase() === account.email; };
  email.addEventListener('input', check);
  check();
  const form = el('form', { className: 'subpanel', testid: 'own-info' }, [
    el('h3', { text: 'Your details' }),
    el('div', { className: 'grid-fields' }, [field('Name', name), field('Email or username (your login)', email)]),
    passwordField,
    el('button', { type: 'submit', testid: 'own-info-save', text: 'Save details' }),
  ]);
  form.addEventListener('submit', (e) => {
    e.preventDefault();
    app.run(async () => {
      const body = { name: name.value.trim() || null, email: email.value.trim() };
      if (!passwordField.hidden) body.password = password.value;
      const saved = await app.api.editOwnInfo(body);
      account.name = saved.name;
      account.email = saved.email;
      password.value = '';
      check();
      app.status.success('Your details are saved.');
    });
  });
  return form;
}

window.memberInfoButton = memberInfoButton;
window.SelfEditPanel = SelfEditPanel;
window.ownInfoBox = ownInfoBox;
