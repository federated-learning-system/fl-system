package metrics

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

var (
	StragglerTotal = promauto.NewCounter(prometheus.CounterOpts{
		Name: "fl_stragglers_total",
		Help: "Total number of straggler clients detected across all rounds",
	})

	RoundsClosed = promauto.NewCounter(prometheus.CounterOpts{
		Name: "fl_rounds_closed_by_deadline_total",
		Help: "Total number of rounds closed by straggler watch deadline",
	})

	ActiveWatchers = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "fl_straggler_active_watchers",
		Help: "Number of goroutines currently watching round deadlines",
	})
)
