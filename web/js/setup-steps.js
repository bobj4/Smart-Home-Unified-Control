/**
 * Settings > Admin, top: "Setting up", the steps left on a new server, each
 * linking to where it is done. Hidden once every step is done.
 */

async function setupStepsPanel(app) {
  let found;
  try {
    found = await app.api.getSetupSteps(app.home ? app.home.id : null);
  } catch (error) {
    return null; // an extra: the page works without it
  }
  if (found.done === found.total) return null;
  return el('div', { className: 'subpanel setup-steps', testid: 'setup-steps' }, [
    el('h3', { text: `Setting up: ${found.done} of ${found.total} done` }),
    el('ul', { className: 'setup-list' }, found.steps.map((step) => el('li', {
      className: step.done ? 'done' : '', testid: 'setup-step', 'data-step': step.id, 'data-done': String(step.done),
    }, [
      el('span', { className: 'setup-mark', 'aria-hidden': 'true', text: step.done ? '✓' : '○' }),
      step.done ? el('span', { text: step.label }) : el('a', { className: 'link', href: step.href, text: step.label }),
    ]))),
  ]);
}

window.setupStepsPanel = setupStepsPanel;
