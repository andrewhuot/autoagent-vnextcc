import { useState } from 'react';
import { Bell, Mail, MessageSquare, Plus, Send, Trash2, Webhook } from 'lucide-react';
import {
  useNotificationSubscriptions,
  useNotificationHistory,
  useRegisterWebhook,
  useRegisterSlack,
  useRegisterEmail,
  useDeleteSubscription,
  useTestSubscription,
} from '../lib/api';
import { PageHeader } from '../components/PageHeader';
import { LoadingSkeleton } from '../components/LoadingSkeleton';
import { EmptyState } from '../components/EmptyState';
import { formatTimestamp } from '../lib/utils';

const EVENT_TYPES = [
  { value: 'health_drop', label: 'Health Drop' },
  { value: 'optimization_complete', label: 'Optimization Complete' },
  { value: 'deployment', label: 'Deployment' },
  { value: 'safety_violation', label: 'Safety Violation' },
  { value: 'daily_summary', label: 'Daily Summary' },
  { value: 'weekly_summary', label: 'Weekly Summary' },
  { value: 'new_opportunity', label: 'New Opportunity' },
  { value: 'gate_failure', label: 'Gate Failure' },
];

const SEVERITY_LEVELS = ['info', 'warning', 'error', 'critical'];

type ChannelType = 'webhook' | 'slack' | 'email';

export function Notifications() {
  const subscriptions = useNotificationSubscriptions();
  const history = useNotificationHistory(50);
  const deleteSubscription = useDeleteSubscription();
  const testSubscription = useTestSubscription();

  const registerWebhook = useRegisterWebhook();
  const registerSlack = useRegisterSlack();
  const registerEmail = useRegisterEmail();

  const [showAddForm, setShowAddForm] = useState(false);
  const [channelType, setChannelType] = useState<ChannelType>('webhook');
  const [url, setUrl] = useState('');
  const [email, setEmail] = useState('');
  const [selectedEvents, setSelectedEvents] = useState<string[]>([]);
  const [severityFilter, setSeverityFilter] = useState('info');

  const handleAddSubscription = async () => {
    if (selectedEvents.length === 0) {
      alert('Please select at least one event type');
      return;
    }

    const filters = { severity: severityFilter };

    try {
      if (channelType === 'webhook') {
        if (!url) {
          alert('Please enter a webhook URL');
          return;
        }
        await registerWebhook.mutateAsync({ url, events: selectedEvents, filters });
      } else if (channelType === 'slack') {
        if (!url) {
          alert('Please enter a Slack webhook URL');
          return;
        }
        await registerSlack.mutateAsync({ webhook_url: url, events: selectedEvents, filters });
      } else if (channelType === 'email') {
        if (!email) {
          alert('Please enter an email address');
          return;
        }
        await registerEmail.mutateAsync({ address: email, events: selectedEvents, filters });
      }

      // Reset form
      setShowAddForm(false);
      setUrl('');
      setEmail('');
      setSelectedEvents([]);
      setSeverityFilter('info');
    } catch (error) {
      alert(`Failed to add subscription: ${error}`);
    }
  };

  const handleDelete = async (subscriptionId: string) => {
    if (!confirm('Are you sure you want to delete this subscription?')) {
      return;
    }
    try {
      await deleteSubscription.mutateAsync(subscriptionId);
    } catch (error) {
      alert(`Failed to delete subscription: ${error}`);
    }
  };

  const handleTest = async (subscriptionId: string) => {
    try {
      await testSubscription.mutateAsync(subscriptionId);
      alert('Test notification sent successfully!');
    } catch (error) {
      alert(`Failed to send test notification: ${error}`);
    }
  };

  const toggleEvent = (eventValue: string) => {
    if (selectedEvents.includes(eventValue)) {
      setSelectedEvents(selectedEvents.filter((e) => e !== eventValue));
    } else {
      setSelectedEvents([...selectedEvents, eventValue]);
    }
  };

  if (subscriptions.isLoading) {
    return <LoadingSkeleton />;
  }

  const channelIcon = (type: string) => {
    switch (type) {
      case 'webhook':
        return <Webhook className="h-5 w-5 text-blue-500" />;
      case 'slack':
        return <MessageSquare className="h-5 w-5 text-purple-500" />;
      case 'email':
        return <Mail className="h-5 w-5 text-green-500" />;
      default:
        return <Bell className="h-5 w-5 text-gray-500" />;
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Notifications"
        subtitle="Configure alerts for agent health, deployments, and optimization events"
      />

      {/* Add Subscription Button */}
      <div className="flex justify-end">
        <button
          onClick={() => setShowAddForm(!showAddForm)}
          className="flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-gray-900 hover:bg-blue-700"
        >
          <Plus className="h-4 w-4" />
          Add Subscription
        </button>
      </div>

      {/* Add Subscription Form */}
      {showAddForm && (
        <div className="rounded-lg border border-gray-200 bg-white p-6">
          <h3 className="mb-4 text-lg font-semibold text-gray-900">Add Notification Subscription</h3>

          {/* Channel Type Selector */}
          <div className="mb-4">
            <label className="mb-2 block text-sm font-medium text-gray-700">Channel Type</label>
            <div className="flex gap-4">
              {(['webhook', 'slack', 'email'] as ChannelType[]).map((type) => (
                <button
                  key={type}
                  onClick={() => setChannelType(type)}
                  className={`flex items-center gap-2 rounded-md px-4 py-2 text-sm font-medium ${
                    channelType === type
                      ? 'bg-blue-600 text-gray-900'
                      : 'bg-gray-700 text-gray-700 hover:bg-gray-100'
                  }`}
                >
                  {channelIcon(type)}
                  {type.charAt(0).toUpperCase() + type.slice(1)}
                </button>
              ))}
            </div>
          </div>

          {/* URL/Email Input */}
          {(channelType === 'webhook' || channelType === 'slack') && (
            <div className="mb-4">
              <label className="mb-2 block text-sm font-medium text-gray-700">
                {channelType === 'webhook' ? 'Webhook URL' : 'Slack Webhook URL'}
              </label>
              <input
                type="url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder={`https://${channelType === 'slack' ? 'hooks.slack.com' : 'example.com'}/...`}
                className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-500 focus:border-blue-500 focus:outline-none"
              />
            </div>
          )}

          {channelType === 'email' && (
            <div className="mb-4">
              <label className="mb-2 block text-sm font-medium text-gray-700">Email Address</label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="user@example.com"
                className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-500 focus:border-blue-500 focus:outline-none"
              />
            </div>
          )}

          {/* Event Type Checkboxes */}
          <div className="mb-4">
            <label className="mb-2 block text-sm font-medium text-gray-700">Event Types</label>
            <div className="grid grid-cols-2 gap-2">
              {EVENT_TYPES.map((event) => (
                <label key={event.value} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={selectedEvents.includes(event.value)}
                    onChange={() => toggleEvent(event.value)}
                    className="h-4 w-4 rounded border-gray-300 bg-white text-blue-600 focus:ring-blue-500"
                  />
                  <span className="text-sm text-gray-700">{event.label}</span>
                </label>
              ))}
            </div>
          </div>

          {/* Severity Filter */}
          <div className="mb-4">
            <label className="mb-2 block text-sm font-medium text-gray-700">
              Minimum Severity Level
            </label>
            <select
              value={severityFilter}
              onChange={(e) => setSeverityFilter(e.target.value)}
              className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:outline-none"
            >
              {SEVERITY_LEVELS.map((level) => (
                <option key={level} value={level}>
                  {level.charAt(0).toUpperCase() + level.slice(1)}
                </option>
              ))}
            </select>
          </div>

          {/* Action Buttons */}
          <div className="flex justify-end gap-2">
            <button
              onClick={() => setShowAddForm(false)}
              className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              onClick={handleAddSubscription}
              disabled={registerWebhook.isPending || registerSlack.isPending || registerEmail.isPending}
              className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-gray-900 hover:bg-blue-700 disabled:opacity-50"
            >
              Add Subscription
            </button>
          </div>
        </div>
      )}

      {/* Active Subscriptions */}
      <div className="rounded-lg border border-gray-200 bg-white">
        <div className="border-b border-gray-200 p-4">
          <h3 className="text-lg font-semibold text-gray-900">Active Subscriptions</h3>
        </div>

        {subscriptions.data?.subscriptions.length === 0 ? (
          <div className="p-8">
            <EmptyState
              title="No subscriptions"
              subtitle="Add a webhook, Slack, or email subscription to get started"
              icon={Bell}
            />
          </div>
        ) : (
          <div className="divide-y divide-gray-200">
            {subscriptions.data?.subscriptions.map((sub) => (
              <div key={sub.id} className="p-4">
                <div className="flex items-start justify-between">
                  <div className="flex items-start gap-3">
                    {channelIcon(sub.channel_type)}
                    <div>
                      <div className="font-medium text-gray-900">
                        {sub.channel_type.charAt(0).toUpperCase() + sub.channel_type.slice(1)}
                      </div>
                      <div className="mt-1 text-sm text-gray-400">
                        {sub.channel_type === 'email'
                          ? sub.config.address
                          : sub.config.url || sub.config.webhook_url}
                      </div>
                      <div className="mt-2 flex flex-wrap gap-1">
                        {sub.events.map((event) => (
                          <span
                            key={event}
                            className="rounded bg-gray-700 px-2 py-1 text-xs text-gray-700"
                          >
                            {event}
                          </span>
                        ))}
                      </div>
                      {sub.filters.severity && (
                        <div className="mt-2 text-xs text-gray-500">
                          Min severity: {sub.filters.severity}
                        </div>
                      )}
                      <div className="mt-1 text-xs text-gray-500">
                        Created {formatTimestamp(sub.created_at)}
                      </div>
                    </div>
                  </div>
                  <div className="flex gap-2">
                    <button
                      onClick={() => handleTest(sub.id)}
                      disabled={testSubscription.isPending}
                      className="flex items-center gap-1 rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                    >
                      <Send className="h-4 w-4" />
                      Test
                    </button>
                    <button
                      onClick={() => handleDelete(sub.id)}
                      disabled={deleteSubscription.isPending}
                      className="flex items-center gap-1 rounded-md border border-red-600 px-3 py-1.5 text-sm text-red-400 hover:bg-red-900/20 disabled:opacity-50"
                    >
                      <Trash2 className="h-4 w-4" />
                      Delete
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Notification History */}
      <div className="rounded-lg border border-gray-200 bg-white">
        <div className="border-b border-gray-200 p-4">
          <h3 className="text-lg font-semibold text-gray-900">Recent Notifications</h3>
        </div>

        {history.isLoading ? (
          <div className="p-4">
            <LoadingSkeleton />
          </div>
        ) : history.data?.history.length === 0 ? (
          <div className="p-8">
            <EmptyState
              title="No notification history"
              subtitle="Notifications will appear here once they are sent"
              icon={Bell}
            />
          </div>
        ) : (
          <div className="divide-y divide-gray-200">
            {history.data?.history.map((entry, idx) => (
              <div key={idx} className="p-4">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="flex items-center gap-2">
                      <span
                        className={`inline-flex items-center gap-1 rounded-full px-2 py-1 text-xs font-medium ${
                          entry.success
                            ? 'bg-green-900/20 text-green-400'
                            : 'bg-red-900/20 text-red-400'
                        }`}
                      >
                        {entry.success ? '✓' : '✗'} {entry.success ? 'Sent' : 'Failed'}
                      </span>
                      <span className="text-sm font-medium text-gray-900">{entry.event_type}</span>
                    </div>
                    <div className="mt-1 text-sm text-gray-400">
                      Subscription: {entry.subscription_id}
                    </div>
                    {entry.error && (
                      <div className="mt-2 rounded bg-red-900/20 p-2 text-xs text-red-400">
                        {entry.error}
                      </div>
                    )}
                  </div>
                  <div className="text-sm text-gray-500">{formatTimestamp(entry.sent_at)}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
