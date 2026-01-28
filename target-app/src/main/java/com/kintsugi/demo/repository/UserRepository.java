package com.kintsugi.demo.repository;

import com.kintsugi.demo.model.User;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.stereotype.Repository;

import java.util.List;
import java.util.Optional;

@Repository
public interface UserRepository extends JpaRepository<User, Long> {

    Optional<User> findByEmail(String email);

    /**
     * BUG: SQL Injection vulnerability in custom query
     * This is intentionally vulnerable for demonstration.
     */
    @Query(value = "SELECT * FROM users WHERE name LIKE %?1%", nativeQuery = true)
    List<User> searchByName(String name);

    List<User> findByActiveTrue();

    List<User> findByActiveFalse();
}
