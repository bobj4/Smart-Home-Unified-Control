/**
 * Settings > Integrations > GE Cync: the owner logs in to Cync (Cync emails
 * a code, typed in here; only the resulting login is kept, encrypted); an
 * admin finds the account's lights and plugs.
 */

class CyncPanel {
  constructor(app) {
    this.app = app;
  }

  async render(container) {
    const box = el('div', { className: 'subpanel', testid: 'cync-account' });
    container.append(box);
    await this.fill(box);
  }

  async fill(box) {
    const account = this.app.can('admin') ? await this.app.api.getCyncAccount(this.app.home.id) : null;
    box.replaceChildren(el('h3', { text: 'GE Cync account' }));
    if (account) {
      box.append(el('p', {
        className: 'muted', testid: 'cync-configured',
        text: account.configured ? `Connected as ${account.email}` : 'No Cync account saved.',
      }));
      box.append(this.form(box, account));
    }
    if (this.app.can('operator')) {
      box.append(el('button', {
        type: 'button', className: 'secondary', testid: 'cync-sync', text: 'Find lights and plugs',
        onclick: () => this.app.run(async () => {
          const result = await this.app.api.syncCync(this.app.home.id);
          this.app.status.success(`Cync devices: ${result.created} new, ${result.updated} updated.`);
        }),
      }));
    }
  }

  form(box, account) {
    const email = el('input', { type: 'email', testid: 'cync-email', autocomplete: 'off', required: true, value: account.email || '' });
    const password = el('input', { type: 'password', testid: 'cync-password', autocomplete: 'new-password', required: true });
    const code = el('input', { type: 'text', testid: 'cync-code', inputmode: 'numeric', autocomplete: 'one-time-code', maxlength: '8', pattern: '[0-9]{4,8}' });
    const codeField = field('Code Cync emailed you', code);
    codeField.hidden = true;
    const submit = el('button', { type: 'submit', testid: 'cync-save', text: account.configured ? 'Log in again' : 'Log in' });
    const form = el('form', { className: 'grid-fields' }, [field('Cync email', email), field('Cync password', password), codeField, submit]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.app.run(async () => {
        const result = await this.app.api.saveCyncAccount(this.app.home.id, email.value.trim(), password.value, codeField.hidden ? null : code.value.trim());
        if (result.code_sent) {
          codeField.hidden = false;
          code.required = true;
          code.focus();
          submit.textContent = 'Finish login';
          this.app.status.show(`Cync emailed a code to ${email.value.trim()}. Enter it to finish.`, 'success');
          return;
        }
        password.value = '';
        await this.fill(box);
        this.app.status.success('Cync login saved.');
      });
    });
    const wrap = el('div', {}, [form]);
    if (account.configured) {
      wrap.append(el('button', {
        type: 'button', className: 'danger', testid: 'cync-forget', text: 'Remove login',
        onclick: () => this.app.run(async () => {
          await this.app.api.removeCyncAccount(this.app.home.id);
          await this.fill(box);
          this.app.status.success('Cync login removed.');
        }),
      }));
    }
    return wrap;
  }
}

window.CyncPanel = CyncPanel;
