/**
 * Settings > Household members. Everyone sees who is in the home; the owner
 * changes roles, removes members and creates one-time enrollment codes.
 * The owner never sees or sets another person's password or authenticator.
 */

const ROLES = ['admin', 'operator', 'member'];
const ROLE_HELP = {
  admin: 'Admin: everything, including users, safety limits and integrations',
  operator: 'Operator: add, edit and remove devices',
  member: 'Member: use devices',
};

class MembersSection {
  constructor(app) {
    this.app = app;
  }

  async render(container) {
    this.list = el('div', { className: 'member-list' });
    container.append(this.list);
    const loads = [this.loadMembers()];
    if (this.app.can('admin')) {
      container.append(this.createForm());
      this.pending = el('div', { className: 'pending' });
      container.append(this.inviteForm(), el('h3', { text: 'Waiting to join' }), this.pending);
      loads.push(this.loadEnrollments());
    }
    await Promise.all(loads);
  }

  async loadMembers() {
    const owner = this.app.can('admin');
    const [members, states] = await Promise.all([
      this.app.api.getMembers(this.app.home.id),
      owner ? this.app.api.getMemberStatus(this.app.home.id) : {},
    ]);
    members.forEach((m) => { m.active = states[m.user_id] !== false; });
    this.list.replaceChildren(...members.map((m) => this.memberRow(m, owner && m.user_id !== this.app.account.id)));
  }

  memberRow(member, manage) {
    const active = member.active !== false;
    const row = el('div', { className: `member-row${active ? '' : ' inactive'}`, testid: 'member-row', 'data-user-id': member.user_id, 'data-role': member.role, 'data-active': String(active) }, [
      el('div', {}, [
        el('strong', { text: member.name || member.email }),
        el('p', { className: 'muted', text: member.name ? member.email : '' }),
      ]),
    ]);
    if (!manage) {
      row.append(el('span', { className: `badge ${member.role}`, title: ROLE_HELP[member.role], text: member.role }));
      if (!active) row.append(el('span', { className: 'badge', testid: 'member-inactive', text: 'inactive' }));
      const setPassword = this.passwordControl(member);
      if (setPassword) row.append(setPassword);
      return row;
    }
    const role = el('select', { testid: 'member-role', 'aria-label': `Role for ${member.email}` },
      ROLES.map((r) => el('option', { value: r, text: r })));
    role.value = member.role;
    role.addEventListener('change', () => this.app.run(async () => {
      try {
        await this.app.api.changeRole(this.app.home.id, member.user_id, role.value);
      } finally {
        await this.loadMembers(); // redraw first, so "success" means the list is up to date
      }
      this.app.status.success(`${member.email} is now ${role.value}.`);
    }));
    const actions = el('div', { className: 'row' });
    // The confirmation is remembered, so a redraw of the list keeps it open.
    const confirmRemove = () => {
      this.confirming = member.user_id;
      actions.replaceChildren(
        el('span', { text: 'Remove from this home?' }),
        el('button', {
          type: 'button', className: 'danger', testid: 'member-remove-confirm', text: 'Yes, remove',
          onclick: () => this.app.run(async () => {
            await this.app.api.removeMember(this.app.home.id, member.user_id);
            this.confirming = null;
            await this.loadMembers();
            this.app.status.success(`${member.email} was removed.`);
          }),
        }),
        el('button', {
          type: 'button', className: 'secondary', testid: 'member-remove-cancel', text: 'Cancel',
          onclick: () => { this.confirming = null; actions.replaceChildren(role, remove); },
        }),
      );
    };
    const remove = el('button', { type: 'button', className: 'danger', testid: 'member-remove', text: 'Remove', onclick: confirmRemove });
    actions.append(role, remove);
    if (this.confirming === member.user_id) confirmRemove();
    const options = this.app.loginOptions;
    if (options && options.allow_recovery && member.role !== 'admin') {
      const resetOut = el('span', { className: 'secret', testid: 'member-reset-code', hidden: true });
      const reset = el('button', {
        type: 'button', className: 'secondary', testid: 'member-reset', text: 'Reset code',
        onclick: () => this.app.run(async () => {
          const result = await this.app.api.createResetCode(this.app.home.id, member.user_id);
          resetOut.textContent = result.reset_code;
          resetOut.hidden = false;
          this.app.status.success(`Give this code to ${member.email}. It works once, for 24 hours.`);
        }),
      });
      actions.append(reset, resetOut);
    }
    // On or off: an inactive account cannot log in, and is logged out now.
    const toggle = el('button', {
      type: 'button', className: `toggle${active ? ' on' : ''}`, testid: 'member-active', 'aria-pressed': String(active),
      text: active ? 'Active' : 'Inactive', title: active ? 'Turn this account off' : 'Turn this account on',
      'aria-label': `${member.email}: ${active ? 'active' : 'inactive'}`,
      onclick: () => this.app.run(async () => {
        await this.app.api.setMemberActive(this.app.home.id, member.user_id, !active);
        await this.loadMembers();
        this.app.status.success(`${member.email} is now ${active ? 'inactive: logged out and unable to log in' : 'active'}.`);
      }),
    });
    row.append(toggle, actions);
    const setPassword = this.passwordControl(member);
    if (setPassword) row.append(setPassword);
    return row;
  }

  /** Admins set passwords for members and operators (not other admins). */
  passwordControl(member) {
    if (!this.app.can('admin') || member.user_id === this.app.account.id) return null;
    if (!['member', 'operator'].includes(member.role)) return null;
    const box = el('div', { className: 'row' });
    const open = el('button', {
      type: 'button', className: 'secondary', testid: 'member-set-password', text: 'Set password',
      onclick: () => {
        const input = el('input', { type: 'password', testid: 'member-new-password', autocomplete: 'new-password', 'aria-label': `New password for ${member.email}` });
        const save = el('button', {
          type: 'button', testid: 'member-password-save', text: 'Save password',
          onclick: () => this.app.run(async () => {
            await this.app.api.setMemberPassword(this.app.home.id, member.user_id, input.value);
            box.replaceChildren(open);
            this.app.status.success(`New password set for ${member.email}. They are logged out everywhere.`);
          }),
        });
        box.replaceChildren(input, save, el('button', { type: 'button', className: 'secondary', text: 'Cancel', onclick: () => box.replaceChildren(open) }));
        input.focus();
      },
    });
    box.append(open);
    return box;
  }

  createForm() {
    const options = this.app.loginOptions || { require_email: true };
    const login = el('input', { type: 'text', testid: 'create-login', autocomplete: 'off', required: true });
    const name = el('input', { type: 'text', testid: 'create-name', maxlength: '100', autocomplete: 'off' });
    const role = el('select', { testid: 'create-role' }, ['member', 'operator', 'admin'].map((r) => el('option', { value: r, text: r })));
    const password = el('input', { type: 'password', testid: 'create-password', autocomplete: 'new-password' });
    const form = el('form', { className: 'subpanel' }, [
      el('h3', { text: 'Create a user' }),
      el('p', { className: 'muted', text: `Set a starting password and give it to them. ${passwordRulesText(this.app.loginOptions)}` }),
      el('div', { className: 'grid-fields' }, [
        field(options.require_email ? 'Email' : 'Email or username', login), field('Name (optional)', name),
        field('Role', role), field('Password', password),
      ]),
      el('button', { type: 'submit', testid: 'create-submit', text: 'Create user' }),
    ]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.app.run(async () => {
        const body = { login: login.value.trim(), role: role.value, password: password.value };
        if (name.value.trim()) body.name = name.value.trim();
        try {
          await this.app.api.createUser(this.app.home.id, body);
        } finally {
          password.value = '';
        }
        form.reset();
        await this.loadMembers();
        this.app.status.success(`${body.login} can now log in with that password.`);
      });
    });
    return form;
  }

  inviteForm() {
    const email = el('input', { type: 'text', testid: 'invite-email', required: true, autocomplete: 'off' });
    const name = el('input', { type: 'text', testid: 'invite-name', maxlength: '100', autocomplete: 'off' });
    const role = el('select', { testid: 'invite-role' }, ['member', 'operator', 'admin'].map((r) => el('option', { value: r, text: r })));
    const result = el('div');
    const form = el('form', { className: 'subpanel' }, [
      el('h3', { text: 'Add a person' }),
      el('p', { className: 'muted', text: 'Creates a one-time code that works for 24 hours. The person opens this app, chooses "Have an enrollment code?", and sets up their own password and authenticator.' }),
      el('div', { className: 'grid-fields' }, [field('Email', email), field('Name (optional)', name), field('Role', role)]),
      el('button', { type: 'submit', testid: 'invite-submit', text: 'Create code' }),
      result,
    ]);
    form.addEventListener('submit', (event) => {
      event.preventDefault();
      this.app.run(async () => {
        const body = { email: email.value.trim(), role: role.value };
        if (name.value.trim()) body.name = name.value.trim();
        const created = await this.app.api.createEnrollment(this.app.home.id, body);
        result.replaceChildren(
          el('p', { className: 'note', text: `Give this code to ${body.email}. It is shown only now.` }),
          el('p', { className: 'secret', testid: 'invite-code', text: created.enrollment_code }),
        );
        email.value = '';
        name.value = '';
        await this.loadEnrollments();
        this.app.status.success('Enrollment code created.');
      });
    });
    return form;
  }

  async loadEnrollments() {
    const rows = await this.app.api.getEnrollments(this.app.home.id);
    if (rows.length === 0) {
      this.pending.replaceChildren(el('p', { className: 'muted', text: 'Nobody.' }));
      return;
    }
    this.pending.replaceChildren(...rows.map((e) => el('div', { className: 'member-row', testid: 'enrollment-row' }, [
      el('div', {}, [
        el('strong', { text: e.email }),
        el('p', { className: 'muted', text: `${e.role} · code expires ${formatTime(e.expires_at)}` }),
      ]),
      el('button', {
        type: 'button', className: 'secondary', testid: 'enrollment-cancel', text: 'Cancel code',
        onclick: () => this.app.run(async () => {
          await this.app.api.cancelEnrollment(this.app.home.id, e.id);
          await this.loadEnrollments();
          this.app.status.success('Code cancelled.');
        }),
      }),
    ])));
  }
}

window.MembersSection = MembersSection;
