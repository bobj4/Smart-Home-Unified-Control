/**
 * Settings > Integrations > Rheem EcoNet: the owner saves the EcoNet login
 * (checked with Rheem, stored encrypted, never shown again); an admin finds
 * the account's water heaters.
 */

class RheemPanel {
  constructor(app) {
    this.app = app;
  }

  async render(container) {
    const box = el('div', { className: 'subpanel', testid: 'rheem-account' });
    container.append(box);
    await this.fill(box);
  }

  async fill(box) {
    const owner = this.app.can('admin');
    const account = owner ? await this.app.api.getRheemAccount(this.app.home.id) : null;
    box.replaceChildren(el('h3', { text: 'Rheem EcoNet account' }));
    if (account) {
      box.append(el('p', {
        className: 'muted', testid: 'rheem-configured',
        text: account.configured ? `Connected as ${account.email}` : 'No EcoNet account saved.',
      }));
      box.append(this.form(box, account));
    }
    if (this.app.can('operator')) {
      box.append(el('button', {
        type: 'button', className: 'secondary', testid: 'rheem-sync', text: 'Find water heaters',
        onclick: () => this.app.run(async () => {
          const result = await this.app.api.syncRheem(this.app.home.id);
          this.app.status.success(`Water heaters: ${result.created} new, ${result.updated} updated.`);
        }),
      }));
    }
  }

  form(box, account) {
    const email = el('input', { type: 'email', testid: 'rheem-email', autocomplete: 'off', required: true, value: account.email || '' });
    const password = el('input', { type: 'password', testid: 'rheem-password', autocomplete: 'new-password', required: true });
    const form = el('form', { className: 'grid-fields' }, [
      field('EcoNet email', email),
      field('EcoNet password', password),
      el('button', { type: 'submit', testid: 'rheem-save', text: account.configured ? 'Replace login' : 'Save and test' }),
    ]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.app.run(async () => {
        try {
          await this.app.api.saveRheemAccount(this.app.home.id, email.value.trim(), password.value);
        } finally {
          password.value = '';
        }
        await this.fill(box);
        this.app.status.success('EcoNet login saved.');
      });
    });
    const wrap = el('div', {}, [form]);
    if (account.configured) {
      wrap.append(el('button', {
        type: 'button', className: 'danger', testid: 'rheem-forget', text: 'Remove login',
        onclick: () => this.app.run(async () => {
          await this.app.api.removeRheemAccount(this.app.home.id);
          await this.fill(box);
          this.app.status.success('EcoNet login removed.');
        }),
      }));
    }
    return wrap;
  }
}

window.RheemPanel = RheemPanel;
