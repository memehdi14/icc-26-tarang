---
name: Clinical Precision
colors:
  surface: '#0e1416'
  surface-dim: '#0e1416'
  surface-bright: '#343a3c'
  surface-container-lowest: '#090f11'
  surface-container-low: '#171d1e'
  surface-container: '#1b2122'
  surface-container-high: '#252b2d'
  surface-container-highest: '#303638'
  on-surface: '#dee3e6'
  on-surface-variant: '#bcc9cd'
  inverse-surface: '#dee3e6'
  inverse-on-surface: '#2b3133'
  outline: '#869397'
  outline-variant: '#3d494c'
  surface-tint: '#4cd7f6'
  primary: '#4cd7f6'
  on-primary: '#003640'
  primary-container: '#06b6d4'
  on-primary-container: '#00424f'
  inverse-primary: '#00687a'
  secondary: '#d0bcff'
  on-secondary: '#3c0091'
  secondary-container: '#571bc1'
  on-secondary-container: '#c4abff'
  tertiary: '#ffb873'
  on-tertiary: '#4b2800'
  tertiary-container: '#e89337'
  on-tertiary-container: '#5b3200'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#acedff'
  primary-fixed-dim: '#4cd7f6'
  on-primary-fixed: '#001f26'
  on-primary-fixed-variant: '#004e5c'
  secondary-fixed: '#e9ddff'
  secondary-fixed-dim: '#d0bcff'
  on-secondary-fixed: '#23005c'
  on-secondary-fixed-variant: '#5516be'
  tertiary-fixed: '#ffdcbf'
  tertiary-fixed-dim: '#ffb873'
  on-tertiary-fixed: '#2d1600'
  on-tertiary-fixed-variant: '#6a3b00'
  background: '#0e1416'
  on-background: '#dee3e6'
  surface-variant: '#303638'
typography:
  display-vitals:
    fontFamily: Geist
    fontSize: 48px
    fontWeight: '600'
    lineHeight: '1'
    letterSpacing: -0.02em
  headline-lg:
    fontFamily: Geist
    fontSize: 30px
    fontWeight: '600'
    lineHeight: 36px
  headline-md:
    fontFamily: Geist
    fontSize: 24px
    fontWeight: '500'
    lineHeight: 32px
  body-lg:
    fontFamily: Geist
    fontSize: 18px
    fontWeight: '400'
    lineHeight: 28px
  body-md:
    fontFamily: Geist
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  label-caps:
    fontFamily: Geist
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.05em
  label-sm:
    fontFamily: Geist
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
  vitals-mobile:
    fontFamily: Geist
    fontSize: 36px
    fontWeight: '600'
    lineHeight: '1'
rounded:
  sm: 0.25rem
  DEFAULT: 0.5rem
  md: 0.75rem
  lg: 1rem
  xl: 1.5rem
  full: 9999px
spacing:
  unit: 4px
  gutter: 24px
  margin-desktop: 32px
  margin-mobile: 16px
  container-max-width: 1440px
---

## Brand & Style
The design system is a medical-grade visual framework optimized for high-acuity cardiac monitoring. It prioritizes cognitive efficiency, trust, and rapid information retrieval for clinicians.

The style is **Corporate / Modern** with a focus on clinical utility. It avoids decorative "tech" tropes like neon glows or unnecessary telemetry lines, opting instead for high-contrast data visualization and a premium, subdued aesthetic. The interface is designed to disappear, allowing critical physiological data to take precedence. The emotional response is one of calm, professional reliability, ensuring that even in high-stress "Active Event" scenarios, the path to clinical action is clear and unobstructed.

## Colors
This design system utilizes a deep, high-contrast dark mode to reduce eye strain during long clinical shifts and to make physiological waveforms pop.

- **Status Colors:** Use strictly for clinical state. Emerald (#10B981) denotes normal sinus rhythm and stable vitals. Amber (#F59E0B) is reserved for cautionary trends or non-critical arrhythmias. Red (#EF4444) is used exclusively for life-threatening events (Asystole, V-Tach) and critical system failures.
- **Data Layers:** Primary Cyan is used for standard interactive elements and primary data highlights. Purple is used for secondary data sets or historical trend comparisons to ensure categorical separation.
- **Neutrality:** The background and surface colors are tiered to provide depth without using heavy shadows, ensuring the focus remains on the light-emitting data points.

## Typography
The system uses **Geist** for its technical precision and exceptional legibility in low-light environments. The typeface's clean, monospaced-like character widths in numerals ensure that heart rate and blood pressure values do not "jump" or shift the layout during real-time updates.

- **Display Vitals:** Specifically for large-scale numerical readouts (e.g., HR, SpO2).
- **Label Caps:** Used for metadata, units of measurement (BPM, mmHg), and axis labels in sparklines.
- **Hierarchy:** High contrast in weight is used to distinguish between static labels and dynamic data.

## Layout & Spacing
The layout follows a **Fixed Grid** model on desktop to ensure that waveform proportions remain medically accurate and do not stretch distortingly. 

- **Grid:** A 12-column grid with 24px gutters. Vitals tiles typically span 3 columns, while primary ECG waveforms span 9 or 12 columns.
- **Rhythm:** An 8px linear scale is used for all internal component spacing to maintain a clean, rhythmic structure.
- **Density:** Large whitespace (32px+) is maintained between major monitoring categories (e.g., Patient Info vs. Real-time Waveforms) to prevent cognitive overload during active monitoring.
- **Responsive:** On mobile, the layout reflows to a single column. Waveforms transition from 6-second views to 3-second views to maintain peak-to-peak legibility.

## Elevation & Depth
Elevation is conveyed through **Tonal Layers** rather than heavy shadows, mimicking the interface of modern medical consoles.

- **Base Layer:** The deepest background (#09090B).
- **Surface Layer:** Cards and monitoring modules use #111827 to sit slightly above the base.
- **Interaction Layer:** Active or "focused" cards use a subtle 1px border of #374151.
- **Event Elevation:** During an "Active Event," the affected module uses a high-contrast border matching the status color (Amber or Red) with a very soft, low-opacity outer glow of the same color to draw immediate peripheral attention.

## Shapes
The design system uses a **Rounded** (0.5rem) base strategy for standard elements like buttons and input fields, but employs **2xl (1.5rem)** roundedness for primary data cards. This creates a "friendly-clinical" aesthetic that feels premium and modern, similar to high-end consumer health electronics.

- **Cards:** 24px (1.5rem) corner radius.
- **Status Chips:** Full pill-shape (999px) for quick categorization.
- **Buttons:** 8px (0.5rem) corner radius for a sturdy, professional feel.

## Components
- **Monitoring Cards:** These are the primary containers. They feature a `label-caps` header, a large `display-vitals` value, and a 1px solid border (#374151).
- **Sparklines:** Real-time physiological trends should be drawn with a 1.5pt stroke. No area fills under the line; keep the background clear to ensure grid lines are visible.
- **Action Buttons:** Primary actions (e.g., "Silence Alarm") use the Primary Cyan with dark text. Secondary actions use the ghost style with a #374151 border.
- **Event Banner:** A full-width, top-anchored banner that appears only during 'Active Events.' It uses the critical red background with white Geist SemiBold text for maximum urgency.
- **Vitals Grid:** A modular system where each tile can be swapped or rearranged. Tiles must maintain consistent padding (24px) regardless of the data density inside.
- **Inputs:** Dark-filled with subtle borders. Focus states must use the Primary Cyan border with no offset to maintain a clean, clinical profile.