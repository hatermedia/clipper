# Vendored web UI assets

The web UI never loads scripts or styles from a CDN. These files are served
from `/static/vendor/` by the local FastAPI app.

| File | Source | SHA-256 |
|---|---|---|
| `alpine.min.js` | npm `alpinejs@3.14.9`, `dist/cdn.min.js` (MIT) | `3ed1eed252488921df65e363d6715deb04d7f92aaedb9e52199fdf73cb1e0ad3` |
| `tailwind.css` | Compiled with `tailwindcss@3.4.17` (MIT) from `../index.html` | regenerated on each rebuild |

Rebuild the stylesheet after changing classes in `index.html`:

```powershell
cd src/clipper/web/static/vendor
npx tailwindcss@3.4.17 -c tailwind.config.js -i tailwind.input.css -o tailwind.css --minify
```

Upgrade Alpine by replacing `alpine.min.js` with the `dist/cdn.min.js` from
`npm pack alpinejs@<version>` and updating the hash above.
