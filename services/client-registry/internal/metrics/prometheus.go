package metrics

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

var (
	ClientsRegistered = promauto.NewCounter(prometheus.CounterOpts{
		Name: "fl_clients_registered_total",
		Help: "Total number of FL clients registered",
	})

	ClientHeartbeats = promauto.NewCounter(prometheus.CounterOpts{
		Name: "fl_client_heartbeats_total",
		Help: "Total number of client heartbeat updates received",
	})

	ActiveClients = promauto.NewGauge(prometheus.GaugeOpts{
		Name: "fl_active_clients",
		Help: "Number of currently active FL clients",
	})

	HTTPRequestDuration = promauto.NewHistogramVec(prometheus.HistogramOpts{
		Name:    "fl_registry_request_duration_seconds",
		Help:    "Duration of HTTP requests to the client registry",
		Buckets: prometheus.DefBuckets,
	}, []string{"method", "path", "status"})
)
