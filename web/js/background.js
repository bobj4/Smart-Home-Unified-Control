/**
 * My account > Appearance > Background picture: a person's own picture
 * behind the app, switched on and off without losing it. Each person has
 * their own; it is only sent to them.
 */

const BACKGROUND_MAX_BYTES = 3 * 1024 * 1024;

/** Show (or remove) the picture behind the page. */
function applyBackground(background) {
  const on = Boolean(background && background.on && background.version);
  document.body.classList.toggle('has-background', on);
  if (on) document.body.style.setProperty('--bg-image', `url("/api/v1/account/background?v=${encodeURIComponent(background.version)}")`);
  else document.body.style.removeProperty('--bg-image');
}

function readAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error('The picture could not be read'));
    reader.readAsDataURL(file);
  });
}

class BackgroundBox {
  constructor(app) {
    this.app = app;
  }

  element() {
    this.box = el('div', { className: 'subpanel', testid: 'background' });
    this.draw();
    return this.box;
  }

  saved(background) {
    this.app.account.background = background;
    applyBackground(background);
    this.draw();
  }

  draw() {
    const bg = this.app.account.background || { on: false, image: false };
    const file = el('input', { type: 'file', testid: 'background-file', accept: 'image/jpeg,image/png,image/webp', 'aria-label': 'Background picture' });
    file.addEventListener('change', () => {
      const chosen = file.files[0];
      if (!chosen) return;
      if (chosen.size > BACKGROUND_MAX_BYTES) {
        this.app.status.error('The picture is larger than 3 MB.');
        return;
      }
      this.app.run(async () => {
        this.saved(await this.app.api.setBackground(await readAsDataUrl(chosen)));
        this.app.status.success('Background picture saved.');
      });
    });
    const toggle = el('input', { type: 'checkbox', role: 'switch', className: 'switch', testid: 'background-on', checked: Boolean(bg.on), disabled: !bg.image, 'aria-label': 'Show the background picture' });
    toggle.addEventListener('change', () => this.app.run(async () => {
      this.saved(await this.app.api.switchBackground(toggle.checked));
      this.app.status.success(toggle.checked ? 'Background picture on.' : 'Background picture off.');
    }));
    this.box.replaceChildren(
      el('h3', { text: 'Background picture' }),
      el('label', { className: 'check' }, [toggle, ' Show my picture behind the app']),
      field(bg.image ? 'Choose another picture' : 'Choose a picture (JPEG, PNG or WebP, up to 3 MB)', file),
      bg.image ? el('button', {
        type: 'button', className: 'secondary', testid: 'background-remove', text: 'Remove picture',
        onclick: () => this.app.run(async () => {
          this.saved(await this.app.api.removeBackground());
          this.app.status.success('Background picture removed.');
        }),
      }) : null,
    );
  }
}

window.BackgroundBox = BackgroundBox;
