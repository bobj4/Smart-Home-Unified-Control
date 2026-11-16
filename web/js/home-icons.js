/**
 * A home's icon (top right, and Admin > Home): a picture of one's own when
 * the home has one, else a built-in line icon (app/home_icons.py names them).
 */

const HOME_ICONS = {
  house: ['House', 'M3 11l9-7 9 7M5 10v10h14V10M10 20v-6h4v6'],
  cabin: ['Cabin', 'M2 12l10-9 10 9M5 10v10h14V10M5 14h14M5 17h14M9 10h6'],
  apartment: ['Apartment', 'M5 21V3h14v18M9 7h2M13 7h2M9 11h2M13 11h2M9 15h2M13 15h2M10 21v-3h4v3'],
  office: ['Office', 'M3 21h18M5 21V8l7-4 7 4v13M9 12h6M9 16h6'],
  beach: ['Beach house', 'M2 20c3-2 5-2 8 0s5 2 8 0 3-1 4-1M6 15l6-5 6 5M8 14v3h8v-3M17 4a2 2 0 1 0 0 .01'],
  mountain: ['Mountain', 'M2 20l7-12 4 6 3-4 6 10zM8 10l1.5 2 1.5-2'],
  farm: ['Farm', 'M3 21V11l6-5 6 5v10M3 21h18M15 21V9h6v12M18 9V5M7 21v-5h4v5'],
  boat: ['Boat', 'M3 16l2 4h14l2-4zM12 3v13M12 4l6 9h-6'],
};

/** The home's picture, or its built-in icon drawn. */
function homeIcon(home, className = 'home-icon') {
  if (home && home.icon_image) {
    return el('img', { className, src: home.icon_image, alt: '', width: '28', height: '28' });
  }
  const [, path] = HOME_ICONS[(home && home.icon) || 'house'] || HOME_ICONS.house;
  return svg('svg', { viewBox: '0 0 24 24', className, 'aria-hidden': 'true' }, [svg('path', { d: path })]);
}

/** A picture file shrunk to 128 pixels (a PNG data: URL), so it stays small. */
function shrinkPicture(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error('That picture could not be read.'));
    reader.onload = () => {
      const image = new Image();
      image.onerror = () => reject(new Error('That file is not a picture.'));
      image.onload = () => {
        const side = 128;
        const scale = Math.min(1, side / Math.max(image.width, image.height));
        const canvas = document.createElement('canvas');
        canvas.width = Math.max(1, Math.round(image.width * scale));
        canvas.height = Math.max(1, Math.round(image.height * scale));
        canvas.getContext('2d').drawImage(image, 0, 0, canvas.width, canvas.height);
        resolve(canvas.toDataURL('image/png'));
      };
      image.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}

window.HOME_ICONS = HOME_ICONS;
window.homeIcon = homeIcon;
window.shrinkPicture = shrinkPicture;
