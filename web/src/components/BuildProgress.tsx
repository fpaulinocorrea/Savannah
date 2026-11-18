// A five-step strip showing which build phases are finished.
const phases = ['Foundation', 'Guest replies', 'Bank', 'Reports', 'Auto + cloud']

export default function BuildProgress({ done }: { done: number }) {
  return (
    <section className="progress" aria-label={`Build progress: ${done} of ${phases.length} phases done`}>
      <h2>Building Savannah</h2>
      <ol>
        {phases.map((p, i) => (
          <li key={p} className={i < done ? 'is-done' : i === done ? 'is-next' : ''}>
            <span className="bar" />
            <span className="label">{p}</span>
          </li>
        ))}
      </ol>
    </section>
  )
}
