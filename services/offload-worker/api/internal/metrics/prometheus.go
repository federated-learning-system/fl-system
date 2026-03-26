package metrics

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

var (
	OffloadJobsQueued = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "fl_offload_jobs_queued",
		Help: "Number of offload training jobs currently queued",
	})

	OffloadJobDuration = promauto.NewHistogram(prometheus.HistogramOpts{
		Name:    "fl_offload_job_duration_seconds",
		Help:    "Duration of offload training jobs",
		Buckets: []float64{5, 10, 30, 60, 120, 300, 600},
	})

	OffloadJobsCreated = promauto.NewCounter(prometheus.CounterOpts{
		Name: "fl_offload_jobs_created_total",
		Help: "Total number of offload training jobs created",
	})
)
