package scheduler

import (
	"log/slog"

	"github.com/robfig/cron/v3"
)

// Scheduler wraps robfig/cron for periodic round scheduling.
type Scheduler struct {
	cron *cron.Cron
	log  *slog.Logger
}

// New creates a new cron scheduler.
func New(log *slog.Logger) *Scheduler {
	return &Scheduler{
		cron: cron.New(cron.WithSeconds()),
		log:  log,
	}
}

// Schedule adds a job that runs at the given cron spec.
// spec uses 6-field cron format (seconds included) or @every syntax.
func (s *Scheduler) Schedule(spec string, fn func()) error {
	_, err := s.cron.AddFunc(spec, fn)
	if err != nil {
		return err
	}
	s.log.Info("scheduled cron job", "spec", spec)
	return nil
}

// Start begins running scheduled jobs.
func (s *Scheduler) Start() {
	s.cron.Start()
	s.log.Info("cron scheduler started")
}

// Stop halts the scheduler gracefully.
func (s *Scheduler) Stop() {
	ctx := s.cron.Stop()
	<-ctx.Done()
	s.log.Info("cron scheduler stopped")
}
