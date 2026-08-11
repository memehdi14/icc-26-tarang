---
name: Tarang Clinical
colors:
  surface: '#faf8ff'
  surface-dim: '#d2d9f4'
  surface-bright: '#faf8ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f2f3ff'
  surface-container: '#eaedff'
  surface-container-high: '#e1e7ff'
  surface-container-highest: '#dae2fc'
  on-surface: '#131b2e'
  on-surface-variant: '#3e4947'
  inverse-surface: '#283044'
  inverse-on-surface: '#eef0ff'
  outline: '#6e7977'
  outline-variant: '#bcc9c6'
  surface-tint: '#066a61'
  primary: '#004e47'
  on-primary: '#ffffff'
  primary-container: '#008378'
  on-primary-container: '#93e4d8'
  inverse-primary: '#85d5c9'
  secondary: '#ba0035'
  on-secondary: '#ffffff'
  secondary-container: '#de294b'
  on-secondary-container: '#fffbff'
  tertiary: '#623c00'
  on-tertiary: '#ffffff'
  tertiary-container: '#825100'
  on-tertiary-container: '#ffcb8f'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#a1f1e5'
  primary-fixed-dim: '#85d5c9'
  on-primary-fixed: '#00201d'
  on-primary-fixed-variant: '#005049'
  secondary-fixed: '#ffdada'
  secondary-fixed-dim: '#ffb3b6'
  on-secondary-fixed: '#40000c'
  on-secondary-fixed-variant: '#920027'
  tertiary-fixed: '#ffddb8'
  tertiary-fixed-dim: '#fcba66'
  on-tertiary-fixed: '#2a1700'
  on-tertiary-fixed-variant: '#653e00'
  background: '#faf8ff'
  on-background: '#131b2e'
  surface-variant: '#dae2fc'
typography:
  metric-display:
    fontFamily: Geist
    fontSize: 48px
    fontWeight: '700'
    lineHeight: 56px
    letterSpacing: -0.02em
  metric-display-mobile:
    fontFamily: Geist
    fontSize: 36px
    fontWeight: '700'
    lineHeight: 40px
  headline-lg:
    fontFamily: Geist
    fontSize: 24px
    fontWeight: '700'
    lineHeight: 32px
  headline-md:
    fontFamily: Geist
    fontSize: 18px
    fontWeight: '600'
    lineHeight: 24px
  body-md:
    fontFamily: Geist
    fontSize: 16px
    fontWeight: '400'
    lineHeight: 24px
  body-sm:
    fontFamily: Geist
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  label-mono:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
    letterSpacing: 0.05em
  reference-text:
    fontFamily: Geist
    fontSize: 12px
    fontWeight: '500'
    lineHeight: 16px
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  margin-desktop: 32px
  margin-mobile: 16px
  gutter: 16px
  card-padding: 20px
  stack-lg: 24px
  stack-md: 16px
  stack-sm: 8px
  base: 4px
---

## Brand & Style

Tarang Clinical is a precision-focused medical telemetry system designed for high-stakes ICU environments. The brand personality is **technical, reliable, and calm**, prioritizing information density without sacrificing clarity. 

The design style is **Corporate / Modern** with a strong influence of **Utility-Minimalism**. It utilizes a systematic approach to data visualization, where color is used purposefully as a status indicator rather than decoration. The interface feels like a sophisticated instrument—clean, crisp, and high-functioning—evoking a sense of professional trust and technological advancement in healthcare.

## Colors

The palette is anchored by a deep teal (**Primary**), chosen for its clinical and calming associations. A surgical red (**Secondary**) is reserved strictly for high-priority alerts and logout actions. 

The background system uses a "cool-neutral" scale with slight blue tints in the surface containers to reduce eye strain during long shifts. High-contrast text (#131b2e) ensures readability against the soft-blue surfaces. Status indicators use a semantic logic: Primary for normal vitals, Tertiary for warnings/trends, and Error for critical alerts.

## Typography

The system utilizes two typefaces to separate human-readable content from machine-generated data. 

**Geist** is the primary sans-serif used for all UI labels, headlines, and body copy. It provides a clean, technical aesthetic that remains legible at small sizes. 
**JetBrains Mono** is used for secondary data points, unit labels (e.g., bpm, mmHg), and system identifiers. This monospaced choice emphasizes the "instrumentation" feel of the clinical station.

Key metrics are presented in **Metric Display**, a heavy-weight large scale for immediate glanceability from a distance across a hospital room.

## Layout & Spacing

The layout utilizes a **hybrid-fluid grid** system. The sidebar is fixed-width (256px) to ensure consistent navigation, while the main dashboard canvas expands to fill the viewport. 

On desktop, the main content is divided into a three-column structure: 
1. **Nav Sidebar:** Fixed left.
2. **Central Canvas:** KPI cards top-row, Waveforms main body.
3. **Right Sidebar:** Patient info and AI clinical insights.

For mobile, the layout collapses into a single-column stack. The right sidebar content (Patient Summary) moves below the primary vitals, and the navigation shifts to a hidden drawer or bottom bar.

## Elevation & Depth

Hierarchy is established through **Tonal Layering** and **Low-Contrast Outlines** rather than heavy shadows. 

The base background uses `surface-container-lowest` (#ffffff). Active interactive elements and primary cards use `surface` (#faf8ff) with a subtle `outline-variant` (#bcc9c6) border. 

Depth is implied through subtle shifts in surface color:
- **Level 0 (Background):** White (#ffffff).
- **Level 1 (Cards/Sidebar):** Very Light Blue-Gray (#faf8ff).
- **Level 2 (Active States/Insets):** Surface-container-high (#e2e7ff).

A very subtle, diffused shadow (`shadow-sm`) is applied only during hover states on KPI cards to provide tactile feedback without cluttering the clinical environment.

## Shapes

The shape language is **Soft and Precise**. A default radius of 0.25rem is used for small interactive elements like buttons and input fields. Larger containers, such as vitals cards and patient summaries, use `rounded-xl` (0.75rem) to soften the density of the data-rich environment. 

Avatar and status dots utilize a full-circle `rounded-full` to stand out as distinct, non-textual elements.

## Components

### Buttons
- **Primary:** Solid `#00685f` background with white text. Slightly rounded corners (0.25rem).
- **Tertiary/Ghost:** No background, `on-surface-variant` text, with a subtle background shift on hover.

### KPI Cards
Cards feature a standard 20px padding. They include a "Trend indicator" (top right), the "Value" (Metric-Display), and a "Unit/Ref range" footer.

### Waveform Display
A grid-background (`#f1f5f9` lines, 20px intervals) is essential for clinical accuracy. Waveform paths should have a stroke width of 1.5px and use semantic colors (Teal for Heart, Container-Teal for SpO2, Gray for Resp).

### Clinical Alerts (Chips & Cards)
Alerts use "Inset" styling. AI-generated insights are distinguished by a `primary-fixed-dim` border and a dedicated badge. Allergies and critical warnings use high-saturation `error-container` backgrounds to ensure they are never missed.