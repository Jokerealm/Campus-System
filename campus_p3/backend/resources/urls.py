from django.urls import path

from .views import (
    GeneratedQuestionCollectionView,
    GeneratedQuestionDetailView,
    GeneratedQuestionReviewView,
    KnowledgePointListView,
    PracticePackCreateView,
    QuestionImportView,
    QuestionSearchView,
)

urlpatterns = [
    path("generated-questions", GeneratedQuestionCollectionView.as_view(), name="generated-question-list"),
    path(
        "generated-questions/<str:generated_question_id>",
        GeneratedQuestionDetailView.as_view(),
        name="generated-question-detail",
    ),
    path(
        "generated-questions/<str:generated_question_id>/review",
        GeneratedQuestionReviewView.as_view(),
        name="generated-question-review",
    ),
    path("knowledge-points", KnowledgePointListView.as_view(), name="knowledge-point-list"),
    path("practice-packs", PracticePackCreateView.as_view(), name="practice-pack-create"),
    path("questions/import", QuestionImportView.as_view(), name="question-import"),
    path("questions/search", QuestionSearchView.as_view(), name="question-search"),
]
