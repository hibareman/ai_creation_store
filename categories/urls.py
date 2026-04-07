from django.urls import path
from .views import CategoryListCreateView, CategoryRetrieveUpdateDestroyView

urlpatterns = [
    # List and create categories for a store
    path(
        'stores/<int:store_id>/categories/',
        CategoryListCreateView.as_view(),
        name='category-list-create'
    ),
    
    # Retrieve, update, and delete a specific category
    path(
        'stores/<int:store_id>/categories/<int:category_id>/',
        CategoryRetrieveUpdateDestroyView.as_view(),
        name='category-detail'
    ),
]
