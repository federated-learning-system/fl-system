package round

import (
	"fmt"
	"sync"
)

// State represents a round's lifecycle phase.
type State string

const (
	StateWaiting     State = "WAITING"
	StateOpen        State = "OPEN"
	StateCollecting  State = "COLLECTING"
	StateClosed      State = "CLOSED"
	StateAggregating State = "AGGREGATING"
	StateDone        State = "DONE"
	StateFailed      State = "FAILED"
)

// Valid transitions between round states.
var validTransitions = map[State][]State{
	StateWaiting:     {StateOpen},
	StateOpen:        {StateCollecting, StateClosed, StateFailed},
	StateCollecting:  {StateClosed, StateFailed},
	StateClosed:      {StateAggregating, StateFailed},
	StateAggregating: {StateDone, StateFailed},
	StateDone:        {},
	StateFailed:      {},
}

// Machine tracks the FSM for a single FL round.
type Machine struct {
	mu      sync.Mutex
	roundID string
	state   State
}

// NewMachine creates a state machine for the given round, starting at the given state.
func NewMachine(roundID string, initial State) *Machine {
	return &Machine{roundID: roundID, state: initial}
}

// State returns the current state (thread-safe).
func (m *Machine) State() State {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.state
}

// Transition attempts to move to the target state.
// Returns an error if the transition is not valid.
func (m *Machine) Transition(target State) error {
	m.mu.Lock()
	defer m.mu.Unlock()

	allowed, ok := validTransitions[m.state]
	if !ok {
		return fmt.Errorf("unknown state: %s", m.state)
	}

	for _, s := range allowed {
		if s == target {
			m.state = target
			return nil
		}
	}

	return fmt.Errorf("invalid transition: %s → %s (round %s)", m.state, target, m.roundID)
}

// CanAcceptUpdates returns true if the round is in a state that accepts client updates.
func (m *Machine) CanAcceptUpdates() bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.state == StateOpen || m.state == StateCollecting
}

// IsTerminal returns true if the round is in a final state.
func (m *Machine) IsTerminal() bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.state == StateDone || m.state == StateFailed
}

// Manager tracks state machines for all active rounds.
type Manager struct {
	mu     sync.RWMutex
	rounds map[string]*Machine
}

// NewManager creates a round manager.
func NewManager() *Manager {
	return &Manager{rounds: make(map[string]*Machine)}
}

// GetOrCreate returns the state machine for a round, creating it if needed.
func (mgr *Manager) GetOrCreate(roundID string, initial State) *Machine {
	mgr.mu.Lock()
	defer mgr.mu.Unlock()
	if m, ok := mgr.rounds[roundID]; ok {
		return m
	}
	m := NewMachine(roundID, initial)
	mgr.rounds[roundID] = m
	return m
}

// Get returns the state machine for a round, or nil if not tracked.
func (mgr *Manager) Get(roundID string) *Machine {
	mgr.mu.RLock()
	defer mgr.mu.RUnlock()
	return mgr.rounds[roundID]
}

// Remove removes a round from tracking (call after terminal state).
func (mgr *Manager) Remove(roundID string) {
	mgr.mu.Lock()
	defer mgr.mu.Unlock()
	delete(mgr.rounds, roundID)
}
