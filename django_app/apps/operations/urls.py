from django.conf.urls import url

from operations.views import MessageView, MessageListView, DictionaryView, DictionaryFormView, HighscoreView, \
    AjaxUnreadMessageView

urlpatterns = [
    url(r'^messages/(?P<message_id>\d*)/', MessageView.as_view(), name="operations.message"),
    url(r'^messages/list/$', MessageListView.as_view(), name="operations.message_list"),
    url(r'^dict/(?P<spelling>.*)/', DictionaryView.as_view(), name="operations.dictionary"),
    url(r'^dict/$', DictionaryFormView.as_view(), name="operations.dictionary_form"),
    url(r'^highscore/$', HighscoreView.as_view(), name="operations.highscore"),
    url(r'^ajax-unread-messages/$', AjaxUnreadMessageView.as_view(), name="operations.ajax_unread_messages"),
]