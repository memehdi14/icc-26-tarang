---
name: Clinical Precision
colors:
  surface: '#131313'
  surface-dim: '#131313'
  surface-bright: '#3a3939'
  surface-container-lowest: '#0e0e0e'
  surface-container-low: '#1c1b1b'
  surface-container: '#201f1f'
  surface-container-high: '#2a2a2a'
  surface-container-highest: '#353534'
  on-surface: '#e5e2e1'
  on-surface-variant: '#bac9c9'
  inverse-surface: '#e5e2e1'
  inverse-on-surface: '#313030'
  outline: '#859493'
  outline-variant: '#3b4949'
  surface-tint: '#2ddbde'
  primary: '#47eaed'
  on-primary: '#003738'
  primary-container: '#00ced1'
  on-primary-container: '#005354'
  inverse-primary: '#00696b'
  secondary: '#5dd9d8'
  on-secondary: '#003737'
  secondary-container: '#00a1a1'
  on-secondary-container: '#002f2f'
  tertiary: '#ffcb9e'
  on-tertiary: '#4b2800'
  tertiary-container: '#ffa54a'
  on-tertiary-container: '#6f3d00'
  error: '#ffb4ab'
  on-error: '#690005'
  error-container: '#93000a'
  on-error-container: '#ffdad6'
  primary-fixed: '#5af8fb'
  primary-fixed-dim: '#2ddbde'
  on-primary-fixed: '#002020'
  on-primary-fixed-variant: '#004f51'
  secondary-fixed: '#7df5f5'
  secondary-fixed-dim: '#5dd9d8'
  on-secondary-fixed: '#002020'
  on-secondary-fixed-variant: '#004f4f'
  tertiary-fixed: '#ffdcc0'
  tertiary-fixed-dim: '#ffb876'
  on-tertiary-fixed: '#2d1600'
  on-tertiary-fixed-variant: '#6b3b00'
  background: '#131313'
  on-background: '#e5e2e1'
  surface-variant: '#353534'
typography:
  display-lg:
    fontFamily: Geist
    fontSize: 48px
    fontWeight: '600'
    lineHeight: '1.1'
    letterSpacing: -0.02em
  headline-md:
    fontFamily: Geist
    fontSize: 24px
    fontWeight: '500'
    lineHeight: '1.2'
    letterSpacing: -0.01em
  data-lg:
    fontFamily: JetBrains Mono
    fontSize: 32px
    fontWeight: '600'
    lineHeight: '1'
    letterSpacing: -0.04em
  body-md:
    fontFamily: JetBrains Mono
    fontSize: 14px
    fontWeight: '400'
    lineHeight: '1.5'
    letterSpacing: 0em
  label-caps:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '700'
    lineHeight: '1'
    letterSpacing: 0.08em
  label-sm:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '500'
    lineHeight: '1'
    letterSpacing: 0em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  unit: 4px
  gutter: 12px
  margin: 24px
  panel-padding: 16px
  density-high: 4px
  density-med: 8px
---

## Brand & Style
The design system is engineered for high-stakes medical environments where clarity, speed of cognition, and technical reliability are paramount. It follows a **Modern Corporate** aesthetic with a heavy emphasis on **High-Density Data** and **Instrumental Minimalism**. 

The UI should evoke the feeling of a high-end surgical console or a diagnostic monitor—precise, cold, and hyper-functional. Surfaces are dark to reduce eye strain in clinical settings, while interactive elements use surgical-grade color accents. The emotional response is one of total control and absolute accuracy.

## Colors
The palette is anchored by a deep "True Black" (#0A0A0A) background to provide maximum contrast for critical data. 

- **Primary Accent:** A refined Medical Teal (#00CED1) used for active states, primary actions, and critical focus areas.
- **Surface Tiers:** Use subtle shifts in dark grays to differentiate panels without losing the "infinite depth" of the black canvas.
- **Semantic Colors:** 
  - **Emerald Success:** A calm, grounded green for healthy vitals.
  - **Amber Warning:** A professional, non-vibrant orange for cautionary data.
  - **Deep Red Alert:** A high-visibility, authoritative red for critical alarms.
- **Borders:** Use low-opacity white (15-20%) for thin, technical outlines.

## Typography
The typography is designed for technical density and rapid scanning. This design system utilizes **Geist** for structural headings to maintain a modern, clean look, while **JetBrains Mono** is used for all data-driven content, labels, and body text.

The use of a monospaced font for data ensures that numerical values (heart rates, dosages, timestamps) do not "jump" or shift when updated in real-time. Headlines should be tight and impactful. Labels should often use uppercase with increased tracking for maximum legibility at small sizes.

## Layout & Spacing
This design system employs a **Fixed Grid** with high-density spacing. The base unit is a strict 4px grid. 

- **Density:** Components should be packed tightly to allow as much information as possible on a single screen without overlapping.
- **Panels:** Data is organized into logical "instrument clusters" (panels) separated by 12px gutters.
- **Mobile Adaptivity:** On mobile devices, panels stack vertically, and the `data-lg` font size scales down to 24px to prevent overflow. Margins reduce to 16px.

## Elevation & Depth
Elevation is achieved through **Tonal Layers** and **Thin Outlines** rather than shadows. 

1. **Base:** True Black (#0A0A0A).
2. **Panel Surface:** Slightly elevated gray (#161616).
3. **Overlays/Modals:** A lighter technical gray (#222222) with a 1px solid border in a neutral-mid tone.

Avoid using soft shadows or blurs. Depth is communicated strictly through the stacking of these solid, low-contrast surfaces. Borders should be hair-thin (0.5pt to 1pt) to reinforce the instrumental feel.

## Shapes
Shapes are "Instrumental"—sharp enough to feel professional and technical, but with a slight 4px (`rounded-sm`) radius to prevent a dated, "raw" look. 

- **Primary Radius:** 4px (Soft) for buttons, input fields, and small containers.
- **Container Radius:** 8px (`rounded-lg`) for main dashboard panels.
- **Status Indicators:** Small 2px radii for status chips or "pills" to maintain a dense, compact footprint.

## Components
- **Buttons:** Ghost-style by default with 1px medical teal borders. Primary buttons are solid Teal with black text for maximum contrast.
- **Input Fields:** Dark backgrounds (#000000) with a subtle bottom-border focus state in Teal. Labels sit outside the input area in `label-caps`.
- **Data Chips:** Small, rectangular tags with monochromatic backgrounds and high-contrast text to denote categories (e.g., [ECG], [SPO2]).
- **Vitals Displays:** Large numeric displays using `data-lg`. Include a small "trend arrow" icon and a sparkline chart directly adjacent to the value.
- **Progress Bars:** Thin, 2px height lines. Use the semantic color palette (Green/Amber/Red) to indicate fill level thresholds.
- **Checkboxes:** Squared with a 2px radius. When checked, the fill is the primary teal with a black "X" or checkmark.