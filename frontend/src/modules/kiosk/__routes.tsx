/**
 * Kiosk — route surface for /kiosk/tokens/:displayId (UI_UX_design §7
 * "Counter token display (kiosk)", UI-003).
 *
 * Standalone and outside the interactive-auth shell: a wall display renders
 * no sidebar and no login prompt in any state (§824). App.tsx lazy-loads
 * this file as the route element; the screen and its polling live in
 * TokenDisplay.tsx / kiosk.api.ts.
 */

export { default } from "./TokenDisplay";
