from dal import autocomplete
from django.contrib.auth import get_user_model

User = get_user_model()


class UserAutocomplete(autocomplete.Select2QuerySetView):
    """Autocomplete view for selecting users in transaction splits."""
    
    def get_queryset(self):
        """Return active, non-deleted users filtered by search query.
        
        This view always shows ALL active users, regardless of who created them.
        This is intentional for transaction splits where any user can be selected.
        """
        # Always return all active, non-deleted users (not filtered by created_by)
        # Use all() to bypass any default manager filtering
        qs = User.objects.all().filter(is_active=True, is_deleted=False)
        
        if self.q:
            # Search by email (primary identifier) or first/last name if available
            from django.db.models import Q
            search_q = Q(email__icontains=self.q)
            # If User model has first_name/last_name fields, include them
            if hasattr(User, 'first_name'):
                search_q = search_q | Q(first_name__icontains=self.q)
            if hasattr(User, 'last_name'):
                search_q = search_q | Q(last_name__icontains=self.q)
            qs = qs.filter(search_q).distinct()
        
        return qs.order_by('email')
