from django.urls import path

from .views import (
    ExplanationNextView,
    PracticeAnswerView,
    PracticeRecommendationView,
    WrongQuestionConfirmView,
    WrongQuestionDetailView,
    WrongQuestionFileView,
    WrongQuestionUploadView,
)


urlpatterns = [
    path(
        "wrong-question-files/<str:token>",
        WrongQuestionFileView.as_view(),
        name="wrong-question-file",
    ),
    path(
        "wrong-questions",
        WrongQuestionUploadView.as_view(),
        name="wrong-question-upload",
    ),
    path(
        "wrong-questions/<str:wrong_question_id>",
        WrongQuestionDetailView.as_view(),
        name="wrong-question-detail",
    ),
    path(
        "wrong-questions/<str:wrong_question_id>/confirm",
        WrongQuestionConfirmView.as_view(),
        name="wrong-question-confirm",
    ),
    path(
        "wrong-questions/<str:wrong_question_id>/explanation/next",
        ExplanationNextView.as_view(),
        name="wrong-question-explanation-next",
    ),
    path(
        "practice/recommendations",
        PracticeRecommendationView.as_view(),
        name="practice-recommendations",
    ),
    path(
        "practice/answers",
        PracticeAnswerView.as_view(),
        name="practice-answers",
    ),
]
