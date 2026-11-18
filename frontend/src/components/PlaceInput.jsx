import { useEffect, useId, useRef, useState } from 'react'
import { suggestPlaces } from '../api.js'

const MIN_CHARS = 3
const DEBOUNCE_MS = 300

// Text box with a dropdown of US place suggestions (WAI-ARIA combobox pattern).
// Suggestions are a convenience only: any typed text can still be submitted.
export default function PlaceInput({ label, value, onChange, placeholder }) {
  const id = useId()
  const listId = `${id}-list`
  const [items, setItems] = useState([])
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const [loading, setLoading] = useState(false)
  const typed = useRef(false) // only search after the user types, not for prefilled values
  const blurTimer = useRef(null)
  const inputRef = useRef(null)

  useEffect(() => {
    if (!typed.current) return
    const q = value.trim()
    if (q.length < MIN_CHARS) {
      setItems([])
      setOpen(false)
      return
    }
    const controller = new AbortController()
    const timer = setTimeout(async () => {
      setLoading(true)
      const results = await suggestPlaces(q, controller.signal)
      if (controller.signal.aborted) return
      setLoading(false)
      setItems(results)
      setActive(-1)
      // Results can arrive after the user has moved on: only show them in the focused box.
      setOpen(document.activeElement === inputRef.current)
    }, DEBOUNCE_MS)
    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [value])

  useEffect(() => () => clearTimeout(blurTimer.current), [])

  function choose(item) {
    typed.current = false
    onChange(item.label)
    setOpen(false)
    setItems([])
  }

  function onKeyDown(e) {
    if (!open || !items.length) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((i) => (i + 1) % items.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((i) => (i <= 0 ? items.length - 1 : i - 1))
    } else if (e.key === 'Enter' && active >= 0) {
      e.preventDefault()
      choose(items[active])
    } else if (e.key === 'Escape') {
      setOpen(false)
    }
  }

  const showList = open && (items.length > 0 || !loading)

  return (
    <div className="field place-field">
      <label htmlFor={id}>{label}</label>
      <input
        ref={inputRef}
        id={id}
        value={value}
        onChange={(e) => {
          typed.current = true
          onChange(e.target.value)
        }}
        onKeyDown={onKeyDown}
        onFocus={() => items.length && setOpen(true)}
        onBlur={() => { blurTimer.current = setTimeout(() => setOpen(false), 150) }}
        required
        maxLength={200}
        placeholder={placeholder}
        autoComplete="off"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={showList}
        aria-controls={listId}
        aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
      />
      {showList && (
        <ul className="suggestions" id={listId} role="listbox" aria-label={`${label} suggestions`}>
          {items.length === 0 && <li className="suggestion-empty">No matching places in the United States</li>}
          {items.map((item, i) => (
            <li
              key={item.label}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? 'active' : ''}
              onMouseDown={(e) => {
                e.preventDefault() // keep focus in the input
                choose(item)
              }}
              onMouseEnter={() => setActive(i)}
            >
              <span className="suggestion-label">{item.label}</span>
              {item.kind && <span className="suggestion-kind">{kindLabel(item.kind)}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function kindLabel(kind) {
  return {
    Municipality: 'City',
    MunicipalitySubdivision: 'Area',
    CountrySubdivision: 'State',
    CountrySecondarySubdivision: 'County',
    PostalCodeArea: 'ZIP code',
    Street: 'Street',
    'Point Address': 'Address',
    'Address Range': 'Address',
  }[kind] || ''
}
