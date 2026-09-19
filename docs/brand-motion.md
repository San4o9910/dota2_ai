# NARMA Vision motion

The public home and authenticated workspace share `mountNarmaSignature(host, { compact })` from `brand-motion.js`. The existing `paintNarmaMark`, completion accent and episode accent exports keep their contracts.

The signature is decorative, with one accessible image name. It has no button, replay caption, focus stop, overlay, network request or new dependency. Its stable fallback is the NV monogram, orange cut, and NARMA VISION name. The larger frame uses a responsive SVG viewBox; the compact variant hides the index and tagline.

The introduction starts once when at least a quarter of its host is visible. A fresh document or mount can introduce the brand again; scrolling and workspace tab changes do not replay it. It never blocks page controls. Its total duration is 4,900 ms:

- 0–900 ms: a narrow vertical orange line descends from above.
- 700–2,160 ms: outlines draw NARMA / VISION and softly fill.
- 2,160–2,840 ms: the complete name holds.
- 2,840–3,920 ms: suffixes dissolve as N and V move together.
- 3,920–4,900 ms: a diagonal orange cut passes through NV; the two halves separate slightly and settle.

The full name remains available below the final monogram. `prefers-reduced-motion` renders the final frame immediately. Changing that preference while running, hiding the document or leaving the page cancels motion and restores the stable frame. No continuous loops or flashing effects are used.

Editorial headings and selected text blocks enter with a 720 ms fade from 85% opacity and a small rise (text stays readable throughout), staggered by at most 260 ms. Blocks containing links or controls only fade, so their hit boxes do not move during initial rendering. Content is visible by default; IntersectionObserver only adds progressive enhancement. Dynamic blocks are discovered after rendering; status messages and live regions are excluded. Existing elements reveal once, and removed observed nodes are released.

Buttons, action links, navigation and summaries respond to primary pointer-down and Enter/Space with a 320 ms press/release and a subtle brightness change. Native events are neither prevented nor delayed. Disabled controls do not animate, repeated keydown does not retrigger, and dynamically rendered controls use the same delegated feedback. Reduced motion cancels both entry and press effects. Keyboard focus outlines remain visible.

Verification lives in the existing public and private browser suites. Public checks capture four frames on 390 and 1440 px layouts, check 320 px overflow, verify the one accessible name, absence of replay controls, duration, full-name/monogram ordering, reduced-motion fallback, progressive reveals, and actual keyboard selection. Private checks verify the initially hidden signature introduces itself after login and completion/episode accents still work. Existing WCAG scans and navigation/upload/coach regressions run unchanged except for the updated signature contract.
