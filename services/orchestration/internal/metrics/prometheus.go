package metrics

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

var (
	RoundsStarted = promauto.NewCounter(prometheus.CounterOpts{
		Name: "fl_rounds_started_total",
		Help: "Total number of FL rounds started by the orchestration controller",
	})

	RoundsClosed = promauto.NewCounter(prometheus.CounterOpts{
		Name: "fl_rounds_closed_total",
		Help: "Total number of FL rounds closed by the orchestration controller",
	})

	RoundScheduleInterval = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "fl_round_schedule_interval_seconds",
		Help: "Current cron interval between round triggers in seconds",
	})

	ActiveRound = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "fl_active_round",
		Help: "1 if a round is currently in progress, 0 otherwise",
	})
)
